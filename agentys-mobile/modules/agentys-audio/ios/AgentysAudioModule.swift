import ExpoModulesCore
import AVFoundation

/// Module natif iOS qui expose des contrôles AVAudioSession non disponibles
/// dans `expo-av`.
///
/// Problème résolu :
/// - `expo-av` active la category `playAndRecord` quand `allowsRecordingIOS:
///   true`. Par défaut sur iOS, cette category route Sound output vers
///   l'écouteur téléphonique (earpiece, faible volume) au lieu du speaker.
/// - `expo-av` n'expose ni `defaultToSpeaker` ni `overrideOutputAudioPort`.
/// - Sans ces options, impossible d'avoir TTS audible + recording simultané
///   → barge-in vocal cassé sur iPhone.
///
/// Solution : ce module expose deux APIs :
///   - `forceSpeakerOutput(enable: Bool)` : active/désactive
///     `AVAudioSession.overrideOutputAudioPort(.speaker)` qui force la
///     sortie vers le haut-parleur même en `playAndRecord`.
///   - `setVoiceChatMode(enable: Bool)` : active la `Mode.voiceChat`, qui
///     applique l'AEC hardware d'iOS (Acoustic Echo Cancellation, le même
///     que FaceTime/Skype) — le mic capture l'environnement EN SUPPRIMANT
///     l'audio sortant du speaker. Whisper reçoit alors uniquement la voix
///     utilisateur, jamais l'écho TTS.
///
/// Combinaison `forceSpeakerOutput(true)` + `setVoiceChatMode(true)` =
/// barge-in vocal fiable.
///
/// Step 4 (streaming STT) : `startMicStream`/`stopMicStream` exposent un tap
/// AVAudioEngine sur le mic — frames PCM16 mono rééchantillonnées à la
/// fréquence demandée (16 kHz pour Deepgram live), émises en base64 via
/// l'event `onMicFrame`. Le JS les relaie au proxy Socket.IO backend.
/// À utiliser avec `configureForVoiceChat()` actif (AEC) pour que la voix
/// capturée soit propre pendant que la TTS joue (barge-in full-duplex).
public class AgentysAudioModule: Module {
  /// Un `setActive(false)` juste après l'arrêt d'une lecture peut échouer en
  /// `AVAudioSessionErrorCodeIsBusy` (le player n'est pas encore démonté).
  /// Un seul retry décalé suffit — au-delà c'est une vraie anomalie, loggée.
  private static let deactivateRetryDelay: TimeInterval = 0.3

  private var audioEngine: AVAudioEngine?
  private var micConverter: AVAudioConverter?
  private var micTargetFormat: AVAudioFormat?

  public func definition() -> ModuleDefinition {
    Name("AgentysAudio")

    Events("onMicFrame", "onMicStreamError")

    /// Trace JS → os_log. console.log de Hermes est invisible en Release ;
    /// NSLog EST capturé par `log collect` / `devicectl --console`. Réintroduit
    /// pour le debug « transcriptions vides après dictée » (2026-07).
    Function("debugLog") { (message: String) in
      NSLog("[drive-dbg] %@", message)
    }

    /// État courant de l'AVAudioSession — category, mode, routes, gain.
    /// Permet au JS de vérifier si le micro est encore branché après un
    /// teardown de recorder.
    Function("audioSessionSnapshot") { () -> String in
      let s = AVAudioSession.sharedInstance()
      let inputs = s.currentRoute.inputs.map { $0.portType.rawValue }.joined(separator: ",")
      let outputs = s.currentRoute.outputs.map { $0.portType.rawValue }.joined(separator: ",")
      return "cat=\(s.category.rawValue) mode=\(s.mode.rawValue) in=[\(inputs)] out=[\(outputs)] gain=\(s.inputGain)"
    }

    /// Force la sortie audio vers le speaker (ou vers la route par défaut).
    /// À appeler APRÈS qu'expo-av a activé la category playAndRecord, sinon
    /// iOS ignore l'override.
    Function("forceSpeakerOutput") { (enable: Bool) -> Bool in
      let session = AVAudioSession.sharedInstance()
      do {
        try session.overrideOutputAudioPort(enable ? .speaker : .none)
        return true
      } catch {
        // -50 (paramError) : la category courante n'accepte pas l'override.
        // En Playback/Ambient c'est bénin (le speaker est déjà la sortie par
        // défaut). En playAndRecord c'est LE cas « TTS dans l'écouteur »
        // (compose 2026-07-29, voix quasi inaudible) : expo-av vient de
        // re-setter la category SANS defaultToSpeaker — on ré-assoit la
        // config complète puis on retente l'override.
        if enable && session.category == .playAndRecord {
          do {
            try session.setCategory(
              .playAndRecord,
              mode: session.mode,
              options: [.defaultToSpeaker, .allowBluetooth, .allowBluetoothA2DP]
            )
            try session.overrideOutputAudioPort(.speaker)
            NSLog("[AgentysAudio] forceSpeakerOutput recovered via re-setCategory")
            return true
          } catch {
            NSLog("[AgentysAudio] forceSpeakerOutput retry failed: \(error)")
            return false
          }
        }
        NSLog("[AgentysAudio] forceSpeakerOutput(\(enable)) failed (cat=\(session.category.rawValue)): \(error)")
        return false
      }
    }

    /// Active le mode voiceChat (AEC hardware) ou retombe en default.
    /// voiceChat suppose category=playAndRecord, sinon iOS log un warning.
    Function("setVoiceChatMode") { (enable: Bool) -> Bool in
      let session = AVAudioSession.sharedInstance()
      do {
        if enable {
          try session.setMode(.voiceChat)
        } else {
          try session.setMode(.default)
        }
        return true
      } catch {
        NSLog("[AgentysAudio] setVoiceChatMode(\(enable)) failed: \(error)")
        return false
      }
    }

    /// Renvoie true si la category courante est `playAndRecord` ET que
    /// l'override speaker est actif. Utile pour debug.
    Function("isSpeakerForced") { () -> Bool in
      let session = AVAudioSession.sharedInstance()
      let route = session.currentRoute
      return route.outputs.contains { $0.portType == .builtInSpeaker }
    }

    /// Configure la session audio pour une lecture+enregistrement simultané
    /// avec speaker fort + AEC. Combine les 2 calls ci-dessus en une seule
    /// API atomique côté JS. Renvoie true si tout a réussi.
    Function("configureForVoiceChat") { () -> Bool in
      let session = AVAudioSession.sharedInstance()
      do {
        // 1) Category playAndRecord avec defaultToSpeaker + allowBluetooth
        //    (écouteurs Bluetooth fonctionnent si l'user en a).
        try session.setCategory(
          .playAndRecord,
          mode: .voiceChat,
          options: [.defaultToSpeaker, .allowBluetooth, .allowBluetoothA2DP]
        )
        // 2) Force speaker output (override pour les cas où le system
        //    auraient déjà routé vers earpiece).
        try session.overrideOutputAudioPort(.speaker)
        // 3) Activate
        try session.setActive(true, options: [.notifyOthersOnDeactivation])
        return true
      } catch {
        NSLog("[AgentysAudio] configureForVoiceChat failed: \(error)")
        return false
      }
    }

    /// Rend l'AVAudioSession au système et PRÉVIENT les autres apps qu'elles
    /// peuvent reprendre (`.notifyOthersOnDeactivation`) — c'est le seul
    /// signal qui fait redémarrer la musique interrompue au début de session.
    ///
    /// Pourquoi ici et pas via expo-av : `EXAudioSessionManager` ne désactive
    /// PLUS la session (son `setActive:NO` est commenté upstream pour éviter
    /// des frame drops, cf. expo/expo#15873) — il remet seulement son flag
    /// interne à NO. Sans cet appel, Spotify resterait muet indéfiniment.
    Function("deactivateSession") { () -> Bool in
      return self.deactivateSession(allowRetry: true)
    }

    /// Reset la session vers une config playback standard (speaker, pas de
    /// recording). À appeler quand le Drive mode se ferme.
    Function("configureForPlayback") { () -> Bool in
      let session = AVAudioSession.sharedInstance()
      do {
        try session.setCategory(.playback, mode: .default, options: [])
        try session.setActive(true, options: [])
        return true
      } catch {
        NSLog("[AgentysAudio] configureForPlayback failed: \(error)")
        return false
      }
    }

    /// Démarre le tap mic AVAudioEngine. Frames PCM16 mono interleaved à
    /// `sampleRate` Hz, émises en base64 via `onMicFrame`. Suppose que la
    /// session audio est déjà configurée (configureForVoiceChat). Retourne
    /// false si l'engine ne démarre pas (pas de permission mic, etc.).
    Function("startMicStream") { (sampleRate: Double) -> Bool in
      return self.startMicStreamInternal(sampleRate: sampleRate)
    }

    /// Coupe le tap mic et libère l'engine. Idempotent.
    Function("stopMicStream") { () -> Bool in
      self.stopMicStreamInternal()
      return true
    }
  }

  @discardableResult
  private func deactivateSession(allowRetry: Bool) -> Bool {
    do {
      try AVAudioSession.sharedInstance().setActive(
        false,
        options: [.notifyOthersOnDeactivation]
      )
      return true
    } catch {
      NSLog("[AgentysAudio] deactivateSession failed (retry=\(allowRetry)): \(error)")
      if allowRetry {
        DispatchQueue.main.asyncAfter(deadline: .now() + Self.deactivateRetryDelay) {
          self.deactivateSession(allowRetry: false)
        }
      }
      return false
    }
  }

  private func startMicStreamInternal(sampleRate: Double) -> Bool {
    stopMicStreamInternal()

    let engine = AVAudioEngine()
    let input = engine.inputNode
    let hwFormat = input.outputFormat(forBus: 0)
    guard hwFormat.sampleRate > 0 else {
      NSLog("[AgentysAudio] startMicStream: invalid hardware format")
      return false
    }
    guard
      let outFormat = AVAudioFormat(
        commonFormat: .pcmFormatInt16,
        sampleRate: sampleRate,
        channels: 1,
        interleaved: true
      ),
      let converter = AVAudioConverter(from: hwFormat, to: outFormat)
    else {
      NSLog("[AgentysAudio] startMicStream: converter init failed")
      return false
    }
    micConverter = converter
    micTargetFormat = outFormat

    // 4096 frames @48 kHz ≈ 85 ms par frame émise — bon compromis
    // latence/overhead (Deepgram recommande 20-250 ms par message).
    input.installTap(onBus: 0, bufferSize: 4096, format: hwFormat) { [weak self] buffer, _ in
      guard
        let self = self,
        let converter = self.micConverter,
        let outFormat = self.micTargetFormat
      else { return }

      let ratio = outFormat.sampleRate / buffer.format.sampleRate
      let capacity = AVAudioFrameCount(Double(buffer.frameLength) * ratio) + 32
      guard let outBuffer = AVAudioPCMBuffer(pcmFormat: outFormat, frameCapacity: capacity) else {
        return
      }

      var consumed = false
      var conversionError: NSError?
      converter.convert(to: outBuffer, error: &conversionError) { _, outStatus in
        if consumed {
          outStatus.pointee = .noDataNow
          return nil
        }
        consumed = true
        outStatus.pointee = .haveData
        return buffer
      }
      if conversionError != nil { return }
      guard let channelData = outBuffer.int16ChannelData, outBuffer.frameLength > 0 else {
        return
      }

      let byteCount = Int(outBuffer.frameLength) * MemoryLayout<Int16>.size
      let data = Data(bytes: channelData[0], count: byteCount)
      self.sendEvent("onMicFrame", ["base64": data.base64EncodedString()])
    }

    engine.prepare()
    do {
      try engine.start()
      audioEngine = engine
      return true
    } catch {
      NSLog("[AgentysAudio] startMicStream failed: \(error)")
      input.removeTap(onBus: 0)
      micConverter = nil
      micTargetFormat = nil
      sendEvent("onMicStreamError", ["error": "\(error)"])
      return false
    }
  }

  private func stopMicStreamInternal() {
    if let engine = audioEngine {
      engine.inputNode.removeTap(onBus: 0)
      engine.stop()
    }
    audioEngine = nil
    micConverter = nil
    micTargetFormat = nil
  }
}
