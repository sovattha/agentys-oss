// Mock expo-speech-recognition (native module)
jest.mock('expo-speech-recognition', () => ({
  ExpoSpeechRecognitionModule: {
    start: jest.fn(),
    stop: jest.fn(),
    abort: jest.fn(),
    getSupportedLocales: jest.fn().mockResolvedValue([]),
    requestPermissionsAsync: jest.fn().mockResolvedValue({ status: 'granted' }),
  },
  useSpeechRecognitionEvent: jest.fn(),
  AudioEncodingAndroid: {},
}));

// Mock expo-av (TTS playback + recording)
jest.mock('expo-av', () => {
  const mockRecording = {
    prepareToRecordAsync: jest.fn().mockResolvedValue(undefined),
    startAsync: jest.fn().mockResolvedValue(undefined),
    stopAndUnloadAsync: jest.fn().mockResolvedValue(undefined),
    getURI: jest.fn().mockReturnValue('file:///mock-recording.m4a'),
  };

  const mockSound = {
    stopAsync: jest.fn().mockResolvedValue(undefined),
    unloadAsync: jest.fn().mockResolvedValue(undefined),
    setOnPlaybackStatusUpdate: jest.fn(),
    setRateAsync: jest.fn().mockResolvedValue(undefined),
    replayAsync: jest.fn().mockResolvedValue(undefined),
    playAsync: jest.fn().mockResolvedValue(undefined),
    setPositionAsync: jest.fn().mockResolvedValue(undefined),
  };

  return {
    Audio: {
      requestPermissionsAsync: jest.fn().mockResolvedValue({ status: 'granted' }),
      setAudioModeAsync: jest.fn().mockResolvedValue(undefined),
      Recording: {
        createAsync: jest.fn().mockResolvedValue({ recording: mockRecording }),
        ...mockRecording,
      },
      RecordingOptionsPresets: {
        HIGH_QUALITY: {},
      },
      Sound: {
        createAsync: jest.fn().mockImplementation(async (_src, _status, cb) => {
          // Par défaut, simule une fin de lecture immédiate
          setTimeout(() => cb?.({ isLoaded: true, didJustFinish: true }), 0);
          return { sound: mockSound };
        }),
      },
    },
    // Valeurs réelles de l'enum expo-av (Audio.types.ts) — src/lib/audioMode.ts
    // les lit au chargement du module.
    InterruptionModeIOS: { MixWithOthers: 0, DoNotMix: 1, DuckOthers: 2 },
    InterruptionModeAndroid: { DoNotMix: 1, DuckOthers: 2 },
  };
});

// Mock expo-secure-store
jest.mock('expo-secure-store', () => ({
  getItemAsync: jest.fn().mockResolvedValue(null),
  setItemAsync: jest.fn().mockResolvedValue(undefined),
  deleteItemAsync: jest.fn().mockResolvedValue(undefined),
}));

// Mock expo-web-browser
jest.mock('expo-web-browser', () => ({
  openAuthSessionAsync: jest.fn(),
  openBrowserAsync: jest.fn(),
  dismissBrowser: jest.fn(),
}));

// Mock expo-crypto
jest.mock('expo-crypto', () => ({
  getRandomBytesAsync: jest.fn(),
  digestStringAsync: jest.fn(),
  CryptoDigestAlgorithm: { SHA256: 'SHA256' },
  CryptoEncoding: { BASE64: 'BASE64' },
}));

// Mock expo-router
const mockRouterBack = jest.fn();
const mockRouterPush = jest.fn();
const mockRouterReplace = jest.fn();

jest.mock('expo-router', () => ({
  useRouter: () => ({
    back: mockRouterBack,
    push: mockRouterPush,
    replace: mockRouterReplace,
  }),
  useLocalSearchParams: jest.fn().mockReturnValue({}),
  router: {
    back: mockRouterBack,
    push: mockRouterPush,
    replace: mockRouterReplace,
  },
}));

// Mock expo-status-bar
jest.mock('expo-status-bar', () => ({
  StatusBar: () => null,
}));

// Mock @expo/vector-icons (not installed — virtual module)
jest.mock('@expo/vector-icons', () => ({
  Ionicons: 'Ionicons',
}), { virtual: true });

// Mock react-native-safe-area-context
jest.mock('react-native-safe-area-context', () => ({
  useSafeAreaInsets: () => ({ top: 0, bottom: 0, left: 0, right: 0 }),
  SafeAreaProvider: ({ children }) => children,
  SafeAreaView: ({ children }) => children,
}));

// Mock expo-linking
jest.mock('expo-linking', () => ({
  createURL: jest.fn().mockReturnValue('agentys://'),
  useURL: jest.fn().mockReturnValue(null),
}));

// Mock expo-haptics
jest.mock('expo-haptics', () => ({
  impactAsync: jest.fn().mockResolvedValue(undefined),
  notificationAsync: jest.fn().mockResolvedValue(undefined),
  selectionAsync: jest.fn().mockResolvedValue(undefined),
  ImpactFeedbackStyle: { Light: 'Light', Medium: 'Medium', Heavy: 'Heavy' },
  NotificationFeedbackType: { Success: 'Success', Warning: 'Warning', Error: 'Error' },
}));

// Mock react-native Alert
jest.spyOn(require('react-native').Alert, 'alert').mockImplementation(() => {});

// Mock react-native-webview
jest.mock('react-native-webview', () => {
  const React = require('react');
  const { View } = require('react-native');
  const MockWebView = React.forwardRef((props, ref) => React.createElement(View, { ...props, ref }));
  MockWebView.displayName = 'WebView';
  return { WebView: MockWebView, default: MockWebView };
});

// Mock global fetch
global.fetch = jest.fn();

// Initialise i18n for tests with FR as active language (matches legacy snapshots
// captured before the extraction). Tests that need EN can call i18n.changeLanguage('en').
const { initI18n, setLanguage } = require('./src/i18n');
initI18n('fr');
// Ensure async changeLanguage resolves synchronously for tests
setLanguage('fr').catch(() => {});
