import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { WebSocketClient, getSocketTransportOptions, getWebSocketClient, resetWebSocketClient } from '../services/websocket'

type EventCallback = (...args: unknown[]) => void

class MockSocket {
  connected = false
  private eventHandlers: Map<string, EventCallback[]> = new Map()

  on(event: string, callback: EventCallback): this {
    if (!this.eventHandlers.has(event)) {
      this.eventHandlers.set(event, [])
    }
    this.eventHandlers.get(event)!.push(callback)
    return this
  }

  disconnect(): void {
    this.connected = false
    this.emit('disconnect')
  }

  removeAllListeners(): this {
    this.eventHandlers.clear()
    return this
  }

  emit(event: string, ...args: unknown[]): void {
    const handlers = this.eventHandlers.get(event)
    if (handlers) {
      handlers.forEach((h) => h(...args))
    }
  }

  simulateConnect(): void {
    this.connected = true
    this.emit('connect')
  }

  simulateDaemonEvent(data: {
    type: string
    email_id: string
    timestamp: string
    payload: Record<string, unknown>
  }): void {
    this.emit('daemon_event', data)
  }
}

let mockSocketInstance: MockSocket | null = null

vi.mock('socket.io-client', () => {
  return {
    io: vi.fn(() => {
      mockSocketInstance = new MockSocket()
      setTimeout(() => mockSocketInstance!.simulateConnect(), 0)
      return mockSocketInstance
    }),
  }
})

function getMockSocket(): MockSocket | null {
  return mockSocketInstance
}

describe('WebSocketClient', () => {
  beforeEach(() => {
    resetWebSocketClient()
    vi.clearAllMocks()
  })

  afterEach(() => {
    vi.clearAllMocks()
  })

  describe('connect', () => {
    it('utilise un WebSocket unique en prod web', async () => {
      const { io } = await import('socket.io-client')
      const client = new WebSocketClient('https://api.agentys.io')

      client.connect()

      expect(getSocketTransportOptions('https://api.agentys.io')).toEqual({
        transports: ['websocket'],
        upgrade: false,
      })
      expect((io as ReturnType<typeof vi.fn>).mock.calls.at(-1)?.[1]).toMatchObject({
        transports: ['websocket'],
        upgrade: false,
        // reconnectionDelayMax stays env-specific (prod = 30s, set in connect()).
        reconnectionDelayMax: 30000,
      })
    })

    it('tente WebSocket en local avec fallback polling (BUG-S010 fix)', async () => {
      const { io } = await import('socket.io-client')
      const client = new WebSocketClient('http://127.0.0.1:5050')

      client.connect()

      // BUG-S010: 9 sessions de tracker silencieux parce que le client ne
      // créait jamais de `new WebSocket()` — `transports: ['polling']` le
      // bloquait sur XHR. On essaie maintenant websocket en premier avec
      // polling comme fallback, et on autorise l'upgrade explicite.
      expect(getSocketTransportOptions('http://127.0.0.1:5050')).toEqual({
        transports: ['websocket', 'polling'],
        upgrade: true,
      })
      expect((io as ReturnType<typeof vi.fn>).mock.calls.at(-1)?.[1]).toMatchObject({
        transports: ['websocket', 'polling'],
        upgrade: true,
        // loopback = 15s (BUG-Y001: responsive reconnect while halving 502 noise).
        reconnectionDelayMax: 15000,
      })
    })

    it('reutilise le singleton quand la meme URL est demandee explicitement', async () => {
      const first = getWebSocketClient('https://api.agentys.io')
      const second = getWebSocketClient('https://api.agentys.io')

      expect(second).toBe(first)
    })

    it('ferme l ancien singleton quand une autre URL est demandee', async () => {
      const first = getWebSocketClient('https://api.agentys.io')
      const disconnectSpy = vi.spyOn(first, 'disconnect')
      const second = getWebSocketClient('https://api-alt.agentys.io')

      expect(second).not.toBe(first)
      expect(disconnectSpy).toHaveBeenCalledTimes(1)
    })

    it('cree une connexion Socket.IO', async () => {
      const client = new WebSocketClient('http://test.local')

      client.connect()

      const mockSocket = getMockSocket()!
      expect(mockSocket).toBeDefined()
    })

    it('ne cree pas de double connexion quand deja connecte', async () => {
      const { io } = await import('socket.io-client')
      const client = new WebSocketClient()

      client.connect()
      await new Promise((r) => setTimeout(r, 10))

      const callCountBefore = (io as ReturnType<typeof vi.fn>).mock.calls.length
      client.connect()
      const callCountAfter = (io as ReturnType<typeof vi.fn>).mock.calls.length

      expect(callCountAfter).toBe(callCountBefore)
    })

    it('ne cree pas de double connexion pendant le handshake initial', async () => {
      const { io } = await import('socket.io-client')
      const client = new WebSocketClient()

      client.connect()
      const callCountBefore = (io as ReturnType<typeof vi.fn>).mock.calls.length
      client.connect()

      expect((io as ReturnType<typeof vi.fn>).mock.calls.length).toBe(callCountBefore)
    })

    it('notifie connection_status quand connecte', async () => {
      const client = new WebSocketClient()
      const handler = vi.fn()

      client.subscribe(handler)
      client.connect()

      await new Promise((r) => setTimeout(r, 10))

      expect(handler).toHaveBeenCalledWith({
        type: 'connection_status',
        data: { connected: true },
      })
    })
  })

  describe('disconnect', () => {
    it('ferme la connexion Socket.IO', async () => {
      const client = new WebSocketClient()

      client.connect()
      await new Promise((r) => setTimeout(r, 10))

      client.disconnect()

      expect(client.isConnected()).toBe(false)
    })

    it('notifie connection_status quand deconnecte', async () => {
      const client = new WebSocketClient()
      const handler = vi.fn()

      client.subscribe(handler)
      client.connect()
      await new Promise((r) => setTimeout(r, 10))

      client.disconnect()

      expect(handler).toHaveBeenCalledWith({
        type: 'connection_status',
        data: { connected: false },
      })
    })

    // Silent-failure fix (issue #317) : l'UI restait indéfiniment sur son dernier
    // état ("Connexion en cours" ou liste vide) quand le backend refusait la
    // connexion (token expiré, CORS, 5xx). Socket.IO émet `connect_error` mais
    // le client ne l'écoutait pas — aucun abonné n'apprenait l'échec.
    it('notifie connection_status avec error quand connect_error', async () => {
      const client = new WebSocketClient()
      const handler = vi.fn()

      client.subscribe(handler)
      client.connect()
      await new Promise((r) => setTimeout(r, 10))

      // On ignore le connect réussi du setup, on veut juste l'erreur après
      handler.mockClear()

      const socket = getMockSocket()!
      socket.emit('connect_error', new Error('CORS blocked'))

      expect(handler).toHaveBeenCalledWith({
        type: 'connection_status',
        data: {
          connected: false,
          error: expect.stringContaining('CORS blocked'),
        },
      })
    })

    // F04 (HIGH): expired JWT → connect_error mentions "unauthorized" →
    // we must dispatch auth:unauthorized AND stop the reconnect loop.
    it('F04: dispatch auth:unauthorized et stoppe la reconnexion sur token expiré', async () => {
      const client = new WebSocketClient()
      const handler = vi.fn()
      const dispatchSpy = vi.spyOn(window, 'dispatchEvent')

      client.subscribe(handler)
      client.connect()
      await new Promise((r) => setTimeout(r, 10))

      handler.mockClear()
      dispatchSpy.mockClear()

      const socket = getMockSocket()!
      // Patch socket.io's `io.opts` so the fix can flip reconnection=false
      ;(socket as any).io = { opts: { reconnection: true } }
      socket.emit('connect_error', new Error('Unauthorized: token expired'))

      // 1) Handler notifié avec un préfixe explicite
      expect(handler).toHaveBeenCalledWith(
        expect.objectContaining({
          type: 'connection_status',
          data: expect.objectContaining({
            connected: false,
            error: expect.stringMatching(/unauthorized/i),
          }),
        }),
      )
      // 2) auth:unauthorized event dispatché (même chemin que le HTTP layer)
      const authCalls = dispatchSpy.mock.calls.filter(
        ([e]: [Event]) => e instanceof CustomEvent && e.type === 'auth:unauthorized',
      )
      expect(authCalls.length).toBeGreaterThanOrEqual(1)
      // 3) Reconnection désactivée
      expect((socket as any).io.opts.reconnection).toBe(false)

      dispatchSpy.mockRestore()
    })

    it('F04: ne dispatch PAS auth:unauthorized sur un connect_error non-auth', async () => {
      const client = new WebSocketClient()
      const handler = vi.fn()
      const dispatchSpy = vi.spyOn(window, 'dispatchEvent')

      client.subscribe(handler)
      client.connect()
      await new Promise((r) => setTimeout(r, 10))
      handler.mockClear()
      dispatchSpy.mockClear()

      const socket = getMockSocket()!
      socket.emit('connect_error', new Error('xhr poll error'))

      const authCalls = dispatchSpy.mock.calls.filter(
        ([e]: [Event]) => e instanceof CustomEvent && e.type === 'auth:unauthorized',
      )
      expect(authCalls.length).toBe(0)
      dispatchSpy.mockRestore()
    })
  })

  describe('subscribe', () => {
    it('recoit les messages new_email', async () => {
      const client = new WebSocketClient()
      const handler = vi.fn()

      client.subscribe(handler)
      client.connect()
      await new Promise((r) => setTimeout(r, 10))

      const mockSocket = getMockSocket()!
      mockSocket.simulateDaemonEvent({
        type: 'new_email',
        email_id: 'email-1',
        timestamp: new Date().toISOString(),
        payload: { sender: 'test@example.com', subject: 'Hello' },
      })

      expect(handler).toHaveBeenCalledWith({
        type: 'new_email',
        data: expect.objectContaining({
          email_id: 'email-1',
          sender: 'test@example.com',
          subject: 'Hello',
          email: expect.objectContaining({
            id: 'email-1',
            sender: 'test@example.com',
            subject: 'Hello',
          }),
        }),
      })
    })

    it('recoit les messages draft_ready', async () => {
      const client = new WebSocketClient()
      const handler = vi.fn()

      client.subscribe(handler)
      client.connect()
      await new Promise((r) => setTimeout(r, 10))

      const mockSocket = getMockSocket()!
      mockSocket.simulateDaemonEvent({
        type: 'draft_ready',
        email_id: 'email-1',
        timestamp: new Date().toISOString(),
        payload: { draft_id: 'draft-1', confidence: 0.9 },
      })

      expect(handler).toHaveBeenCalledWith({
        type: 'draft_ready',
        data: { email_id: 'email-1', draft_id: 'draft-1', confidence: 0.9 },
      })
    })

    it('recoit les messages processing_started', async () => {
      const client = new WebSocketClient()
      const handler = vi.fn()

      client.subscribe(handler)
      client.connect()
      await new Promise((r) => setTimeout(r, 10))

      const mockSocket = getMockSocket()!
      mockSocket.simulateDaemonEvent({
        type: 'processing_started',
        email_id: 'email-1',
        timestamp: new Date().toISOString(),
        payload: {},
      })

      expect(handler).toHaveBeenCalledWith({
        type: 'processing_started',
        data: { email_id: 'email-1' },
      })
    })

    it('recoit les messages processing_error', async () => {
      const client = new WebSocketClient()
      const handler = vi.fn()

      client.subscribe(handler)
      client.connect()
      await new Promise((r) => setTimeout(r, 10))

      const mockSocket = getMockSocket()!
      mockSocket.simulateDaemonEvent({
        type: 'processing_error',
        email_id: 'email-1',
        timestamp: new Date().toISOString(),
        payload: { error: 'Something went wrong' },
      })

      expect(handler).toHaveBeenCalledWith({
        type: 'processing_error',
        data: { email_id: 'email-1', error: 'Something went wrong' },
      })
    })

    it('permet de se desabonner', async () => {
      const client = new WebSocketClient()
      const handler = vi.fn()

      const unsubscribe = client.subscribe(handler)
      client.connect()
      await new Promise((r) => setTimeout(r, 10))

      unsubscribe()

      const mockSocket = getMockSocket()!
      mockSocket.simulateDaemonEvent({
        type: 'new_email',
        email_id: 'email-1',
        timestamp: new Date().toISOString(),
        payload: { sender: 'test@example.com', subject: 'Hello' },
      })

      expect(handler).toHaveBeenCalledTimes(1)
    })

    it('ignore les evenements inconnus', async () => {
      const client = new WebSocketClient()
      const handler = vi.fn()

      client.subscribe(handler)
      client.connect()
      await new Promise((r) => setTimeout(r, 10))

      const mockSocket = getMockSocket()!
      mockSocket.simulateDaemonEvent({
        type: 'unknown_event',
        email_id: 'email-1',
        timestamp: new Date().toISOString(),
        payload: {},
      })

      expect(handler).toHaveBeenCalledTimes(1)
    })
  })

  describe('isConnected', () => {
    it('retourne false avant connexion', () => {
      const client = new WebSocketClient()
      expect(client.isConnected()).toBe(false)
    })

    it('retourne true apres connexion', async () => {
      const client = new WebSocketClient()
      client.connect()

      await new Promise((r) => setTimeout(r, 10))

      expect(client.isConnected()).toBe(true)
    })

    it('retourne false apres deconnexion', async () => {
      const client = new WebSocketClient()
      client.connect()
      await new Promise((r) => setTimeout(r, 10))

      client.disconnect()

      expect(client.isConnected()).toBe(false)
    })
  })
})
