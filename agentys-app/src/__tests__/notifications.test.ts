import { describe, it, expect, vi, beforeEach, beforeAll, afterEach } from 'vitest'
import i18n from '../i18n'
import {
  createNotificationService,
  getNotificationService,
  resetNotificationService,
  type NotificationOptions,
  NOTIFICATION_ACTION_TYPE_ID,
  NOTIFICATION_GROUP_ID,
} from '../services/notifications'

// Notifications use i18n.t() so the rendered strings depend on the active
// locale. Pin to English once so assertions like `title: 'New message'`
// match — without this the tests inherit the default French locale that
// vitest's setup file resolves to and every title check fails.
beforeAll(async () => {
  await i18n.changeLanguage('en')
})

const mockIsPermissionGranted = vi.fn()
const mockRequestPermission = vi.fn()
const mockSendNotification = vi.fn()
const mockOnAction = vi.fn()
const mockRegisterActionTypes = vi.fn()

vi.mock('@tauri-apps/plugin-notification', () => ({
  isPermissionGranted: () => mockIsPermissionGranted(),
  requestPermission: () => mockRequestPermission(),
  sendNotification: (options: NotificationOptions) => mockSendNotification(options),
  onAction: (cb: (notification: unknown) => void) => mockOnAction(cb),
  registerActionTypes: (types: unknown[]) => mockRegisterActionTypes(types),
}))

const mockShouldNotify = vi.fn(() => true)
const mockShouldSuppressForQuietHours = vi.fn(() => false)

vi.mock('../services/workHours', () => ({
  shouldNotify: () => mockShouldNotify(),
}))

vi.mock('../services/quietHours', () => ({
  shouldSuppressForQuietHours: () => mockShouldSuppressForQuietHours(),
}))

// Mock isTauri so the service uses Tauri notification path
vi.mock('../services/tokenStorage', () => ({
  isTauri: () => true,
}))

describe('NotificationService', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockIsPermissionGranted.mockResolvedValue(true)
    mockRequestPermission.mockResolvedValue('granted')
  })

  afterEach(() => {
    vi.clearAllMocks()
  })

  describe('checkPermission', () => {
    it('retourne true si permission accordee', async () => {
      mockIsPermissionGranted.mockResolvedValue(true)
      const service = createNotificationService()

      const result = await service.checkPermission()

      expect(result).toBe(true)
      expect(mockIsPermissionGranted).toHaveBeenCalled()
    })

    it('retourne false si permission refusee', async () => {
      mockIsPermissionGranted.mockResolvedValue(false)
      const service = createNotificationService()

      const result = await service.checkPermission()

      expect(result).toBe(false)
    })
  })

  describe('requestPermission', () => {
    it('demande la permission et retourne true si accordee', async () => {
      mockRequestPermission.mockResolvedValue('granted')
      const service = createNotificationService()

      const result = await service.requestPermission()

      expect(result).toBe(true)
      expect(mockRequestPermission).toHaveBeenCalled()
    })

    it('retourne false si permission refusee', async () => {
      mockRequestPermission.mockResolvedValue('denied')
      const service = createNotificationService()

      const result = await service.requestPermission()

      expect(result).toBe(false)
    })
  })

  describe('notifyNewEmail', () => {
    it('envoie notification pour nouvel email', async () => {
      const service = createNotificationService()

      await service.notifyNewEmail({
        emailId: 'email-123',
        sender: 'client@example.com',
        subject: 'Demande de devis',
      })

      expect(mockSendNotification).toHaveBeenCalledWith(
        expect.objectContaining({
          title: 'New message',
          body: 'client@example.com: Demande de devis',
        })
      )
    })

    it('tronque le sujet si trop long', async () => {
      const service = createNotificationService()
      const longSubject = 'A'.repeat(100)

      await service.notifyNewEmail({
        emailId: 'email-123',
        sender: 'client@example.com',
        subject: longSubject,
      })

      expect(mockSendNotification).toHaveBeenCalledWith(
        expect.objectContaining({
          title: 'New message',
          body: `client@example.com: ${'A'.repeat(47)}...`,
        })
      )
    })

    it('ne notifie pas si desactive', async () => {
      const service = createNotificationService()
      service.setEnabled(false)

      await service.notifyNewEmail({
        emailId: 'email-123',
        sender: 'client@example.com',
        subject: 'Test',
      })

      expect(mockSendNotification).not.toHaveBeenCalled()
    })
  })

  describe('notifyDraftReady', () => {
    it('envoie notification pour brouillon pret', async () => {
      const service = createNotificationService()

      await service.notifyDraftReady({
        emailId: 'email-123',
        sender: 'client@example.com',
        confidence: 0.85,
      })

      expect(mockSendNotification).toHaveBeenCalledWith(
        expect.objectContaining({
          title: 'Draft ready',
          body: 'Suggested reply for client@example.com (85%)',
        })
      )
    })

    it('affiche le pourcentage de confiance arrondi', async () => {
      const service = createNotificationService()

      await service.notifyDraftReady({
        emailId: 'email-123',
        sender: 'client@example.com',
        confidence: 0.876,
      })

      expect(mockSendNotification).toHaveBeenCalledWith(
        expect.objectContaining({
          title: 'Draft ready',
          body: 'Suggested reply for client@example.com (88%)',
        })
      )
    })
  })

  describe('notifyDraftReminder', () => {
    it('envoie notification de rappel pour brouillon en attente', async () => {
      const service = createNotificationService()

      await service.notifyDraftReminder({
        emailId: 'email-123',
        sender: 'client@example.com',
        draftId: 'draft-456',
      })

      expect(mockSendNotification).toHaveBeenCalledWith(
        expect.objectContaining({
          title: 'Reminder: pending draft',
          body: 'Reply for client@example.com awaiting validation',
          actionTypeId: NOTIFICATION_ACTION_TYPE_ID,
          extra: { emailId: 'email-123', type: 'draft_reminder' },
        })
      )
    })

    it('ne notifie pas si desactive', async () => {
      const service = createNotificationService()
      service.setEnabled(false)

      await service.notifyDraftReminder({
        emailId: 'email-123',
        sender: 'client@example.com',
        draftId: 'draft-456',
      })

      expect(mockSendNotification).not.toHaveBeenCalled()
    })
  })

  describe('setEnabled', () => {
    it('permet de desactiver les notifications', async () => {
      const service = createNotificationService()

      service.setEnabled(false)
      await service.notifyNewEmail({
        emailId: 'email-123',
        sender: 'test@example.com',
        subject: 'Test',
      })

      expect(mockSendNotification).not.toHaveBeenCalled()
    })

    it('permet de reactiver les notifications', async () => {
      const service = createNotificationService()

      service.setEnabled(false)
      service.setEnabled(true)
      await service.notifyNewEmail({
        emailId: 'email-123',
        sender: 'test@example.com',
        subject: 'Test',
      })

      expect(mockSendNotification).toHaveBeenCalled()
    })
  })

  describe('isEnabled', () => {
    it('retourne true par defaut', () => {
      const service = createNotificationService()

      expect(service.isEnabled()).toBe(true)
    })

    it('retourne false apres desactivation', () => {
      const service = createNotificationService()

      service.setEnabled(false)

      expect(service.isEnabled()).toBe(false)
    })
  })
})

describe('getNotificationService', () => {
  beforeEach(() => {
    resetNotificationService()
  })

  it('retourne le meme singleton', () => {
    const service1 = getNotificationService()
    const service2 = getNotificationService()

    expect(service1).toBe(service2)
  })
})

describe('Notification click handling', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockIsPermissionGranted.mockResolvedValue(true)
    mockRequestPermission.mockResolvedValue('granted')
    mockOnAction.mockResolvedValue({ unregister: vi.fn() })
    mockRegisterActionTypes.mockResolvedValue(undefined)
    resetNotificationService()
  })

  describe('notifyNewEmail with click action', () => {
    it('envoie notification avec actionTypeId pour permettre le clic', async () => {
      const service = createNotificationService()

      await service.notifyNewEmail({
        emailId: 'email-123',
        sender: 'client@example.com',
        subject: 'Demande de devis',
      })

      expect(mockSendNotification).toHaveBeenCalledWith(
        expect.objectContaining({
          title: 'New message',
          body: 'client@example.com: Demande de devis',
          actionTypeId: NOTIFICATION_ACTION_TYPE_ID,
          extra: { emailId: 'email-123', type: 'new_email' },
        })
      )
    })
  })

  describe('notifyDraftReady with click action', () => {
    it('envoie notification avec actionTypeId pour permettre le clic', async () => {
      const service = createNotificationService()

      await service.notifyDraftReady({
        emailId: 'email-456',
        sender: 'client@example.com',
        confidence: 0.85,
      })

      expect(mockSendNotification).toHaveBeenCalledWith(
        expect.objectContaining({
          title: 'Draft ready',
          actionTypeId: NOTIFICATION_ACTION_TYPE_ID,
          extra: { emailId: 'email-456', type: 'draft_ready' },
        })
      )
    })
  })

  describe('onNotificationClick', () => {
    it('enregistre un callback pour les clics sur notification', async () => {
      const service = createNotificationService()
      const callback = vi.fn()

      await service.onNotificationClick(callback)

      expect(mockOnAction).toHaveBeenCalled()
    })

    it('appelle le callback avec emailId quand notification cliquee', async () => {
      const service = createNotificationService()
      const callback = vi.fn()
      let capturedActionHandler: ((notification: unknown) => void) | null = null

      mockOnAction.mockImplementation((cb) => {
        capturedActionHandler = cb
        return Promise.resolve({ unregister: vi.fn() })
      })

      await service.onNotificationClick(callback)

      expect(capturedActionHandler).not.toBeNull()
      capturedActionHandler!({
        notification: {
          extra: { emailId: 'email-789', type: 'new_email' },
        },
      })

      expect(callback).toHaveBeenCalledWith('email-789')
    })

    it('retourne une fonction pour se desabonner', async () => {
      const service = createNotificationService()
      const mockUnregister = vi.fn()
      mockOnAction.mockResolvedValue({ unregister: mockUnregister })

      const unsubscribe = await service.onNotificationClick(vi.fn())
      unsubscribe()

      expect(mockUnregister).toHaveBeenCalled()
    })
  })

  describe('registerNotificationActions', () => {
    it('enregistre le type action au demarrage', async () => {
      const service = createNotificationService()

      await service.registerNotificationActions()

      const payload = mockRegisterActionTypes.mock.calls[0][0]
      expect(payload).toContainEqual({
        id: NOTIFICATION_ACTION_TYPE_ID,
        actions: [
          {
            id: 'open',
            title: 'Open',
          },
        ],
      })
    })
  })
})

describe('Quick Reply Actions', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockIsPermissionGranted.mockResolvedValue(true)
    mockRequestPermission.mockResolvedValue('granted')
    mockOnAction.mockResolvedValue({ unregister: vi.fn() })
    mockRegisterActionTypes.mockResolvedValue(undefined)
    resetNotificationService()
  })

  describe('registerQuickReplyActions', () => {
    it('enregistre les actions quick reply pour brouillons', async () => {
      const service = createNotificationService()

      await service.registerQuickReplyActions()

      expect(mockRegisterActionTypes).toHaveBeenCalledWith([
        expect.objectContaining({
          id: 'agentys-draft-actions',
          actions: expect.arrayContaining([
            expect.objectContaining({ id: 'validate', title: 'Validate' }),
            expect.objectContaining({ id: 'reject', title: 'Reject' }),
            expect.objectContaining({ id: 'open', title: 'Open' }),
          ]),
        }),
      ])
    })
  })

  describe('notifyDraftReady with quick reply', () => {
    it('envoie notification avec actions quick reply', async () => {
      const service = createNotificationService()

      await service.notifyDraftReadyWithQuickReply({
        emailId: 'email-123',
        draftId: 'draft-456',
        sender: 'client@example.com',
        confidence: 0.85,
        draftContent: 'Bonjour, merci pour votre message...',
      })

      expect(mockSendNotification).toHaveBeenCalledWith(
        expect.objectContaining({
          title: 'Draft ready',
          actionTypeId: 'agentys-draft-actions',
          extra: expect.objectContaining({
            emailId: 'email-123',
            draftId: 'draft-456',
            type: 'draft_quick_reply',
          }),
        })
      )
    })

    it('ne notifie pas si desactive', async () => {
      const service = createNotificationService()
      service.setEnabled(false)

      await service.notifyDraftReadyWithQuickReply({
        emailId: 'email-123',
        draftId: 'draft-456',
        sender: 'client@example.com',
        confidence: 0.85,
        draftContent: 'Bonjour...',
      })

      expect(mockSendNotification).not.toHaveBeenCalled()
    })
  })

  describe('onQuickReplyAction', () => {
    it('appelle le callback validate quand action validate cliquee', async () => {
      const service = createNotificationService()
      const callback = vi.fn()
      let capturedActionHandler: ((notification: unknown) => void) | null = null

      mockOnAction.mockImplementation((cb) => {
        capturedActionHandler = cb
        return Promise.resolve({ unregister: vi.fn() })
      })

      await service.onQuickReplyAction(callback)

      expect(capturedActionHandler).not.toBeNull()
      capturedActionHandler!({
        actionId: 'validate',
        notification: {
          extra: {
            emailId: 'email-123',
            draftId: 'draft-456',
            type: 'draft_quick_reply',
          },
        },
      })

      expect(callback).toHaveBeenCalledWith({
        action: 'validate',
        emailId: 'email-123',
        draftId: 'draft-456',
      })
    })

    it('appelle le callback reject quand action reject cliquee', async () => {
      const service = createNotificationService()
      const callback = vi.fn()
      let capturedActionHandler: ((notification: unknown) => void) | null = null

      mockOnAction.mockImplementation((cb) => {
        capturedActionHandler = cb
        return Promise.resolve({ unregister: vi.fn() })
      })

      await service.onQuickReplyAction(callback)

      capturedActionHandler!({
        actionId: 'reject',
        notification: {
          extra: {
            emailId: 'email-123',
            draftId: 'draft-456',
            type: 'draft_quick_reply',
          },
        },
      })

      expect(callback).toHaveBeenCalledWith({
        action: 'reject',
        emailId: 'email-123',
        draftId: 'draft-456',
      })
    })

    it('appelle le callback open quand action open cliquee', async () => {
      const service = createNotificationService()
      const callback = vi.fn()
      let capturedActionHandler: ((notification: unknown) => void) | null = null

      mockOnAction.mockImplementation((cb) => {
        capturedActionHandler = cb
        return Promise.resolve({ unregister: vi.fn() })
      })

      await service.onQuickReplyAction(callback)

      capturedActionHandler!({
        actionId: 'open',
        notification: {
          extra: {
            emailId: 'email-123',
            draftId: 'draft-456',
            type: 'draft_quick_reply',
          },
        },
      })

      expect(callback).toHaveBeenCalledWith({
        action: 'open',
        emailId: 'email-123',
        draftId: 'draft-456',
      })
    })

    it('ignore les notifications sans type draft_quick_reply', async () => {
      const service = createNotificationService()
      const callback = vi.fn()
      let capturedActionHandler: ((notification: unknown) => void) | null = null

      mockOnAction.mockImplementation((cb) => {
        capturedActionHandler = cb
        return Promise.resolve({ unregister: vi.fn() })
      })

      await service.onQuickReplyAction(callback)

      capturedActionHandler!({
        actionId: 'validate',
        notification: {
          extra: {
            emailId: 'email-123',
            type: 'new_email',
          },
        },
      })

      expect(callback).not.toHaveBeenCalled()
    })

    it('retourne une fonction pour se desabonner', async () => {
      const service = createNotificationService()
      const mockUnregister = vi.fn()
      mockOnAction.mockResolvedValue({ unregister: mockUnregister })

      const unsubscribe = await service.onQuickReplyAction(vi.fn())
      unsubscribe()

      expect(mockUnregister).toHaveBeenCalled()
    })
  })
})

describe('Work Hours Filter Integration', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockIsPermissionGranted.mockResolvedValue(true)
    mockRequestPermission.mockResolvedValue('granted')
    mockOnAction.mockResolvedValue({ unregister: vi.fn() })
    mockRegisterActionTypes.mockResolvedValue(undefined)
    mockShouldNotify.mockReturnValue(true)
    resetNotificationService()
  })

  it('ne notifie pas si en dehors des heures de travail', async () => {
    mockShouldNotify.mockReturnValue(false)

    const service = createNotificationService()
    await service.notifyNewEmail({
      emailId: 'email-123',
      sender: 'client@example.com',
      subject: 'Test',
    })

    expect(mockSendNotification).not.toHaveBeenCalled()
  })

  it('notifie si dans les heures de travail', async () => {
    mockShouldNotify.mockReturnValue(true)

    const service = createNotificationService()
    await service.notifyNewEmail({
      emailId: 'email-123',
      sender: 'client@example.com',
      subject: 'Test',
    })

    expect(mockSendNotification).toHaveBeenCalled()
  })

  it('ne notifie pas brouillon en dehors des heures', async () => {
    mockShouldNotify.mockReturnValue(false)

    const service = createNotificationService()
    await service.notifyDraftReady({
      emailId: 'email-123',
      sender: 'client@example.com',
      confidence: 0.85,
    })

    expect(mockSendNotification).not.toHaveBeenCalled()
  })

  it('ne notifie pas rappel en dehors des heures', async () => {
    mockShouldNotify.mockReturnValue(false)

    const service = createNotificationService()
    await service.notifyDraftReminder({
      emailId: 'email-123',
      sender: 'client@example.com',
      draftId: 'draft-456',
    })

    expect(mockSendNotification).not.toHaveBeenCalled()
  })

  it('ne notifie pas quick reply en dehors des heures', async () => {
    mockShouldNotify.mockReturnValue(false)

    const service = createNotificationService()
    await service.notifyDraftReadyWithQuickReply({
      emailId: 'email-123',
      draftId: 'draft-456',
      sender: 'client@example.com',
      confidence: 0.85,
      draftContent: 'Bonjour...',
    })

    expect(mockSendNotification).not.toHaveBeenCalled()
  })
})

const mockLocalStorage: Record<string, string> = {}
const localStorageMock = {
  getItem: vi.fn((key: string) => mockLocalStorage[key] ?? null),
  setItem: vi.fn((key: string, value: string) => {
    mockLocalStorage[key] = value
  }),
  removeItem: vi.fn((key: string) => {
    delete mockLocalStorage[key]
  }),
  clear: vi.fn(() => {
    Object.keys(mockLocalStorage).forEach((key) => delete mockLocalStorage[key])
  }),
}

function clearMockLocalStorage() {
  Object.keys(mockLocalStorage).forEach((key) => delete mockLocalStorage[key])
  localStorageMock.getItem.mockClear()
  localStorageMock.setItem.mockClear()
}

// Set up localStorage mock
Object.defineProperty(globalThis, 'localStorage', { value: localStorageMock })

describe('Notification Grouping (AC4)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockIsPermissionGranted.mockResolvedValue(true)
    mockRequestPermission.mockResolvedValue('granted')
    mockShouldNotify.mockReturnValue(true)
    resetNotificationService()
    clearMockLocalStorage()
  })

  describe('notifyNewEmail with grouping', () => {
    it('inclut le group ID dans la notification', async () => {
      const service = createNotificationService()

      await service.notifyNewEmail({
        emailId: 'email-123',
        sender: 'client@example.com',
        subject: 'Test',
      })

      expect(mockSendNotification).toHaveBeenCalledWith(
        expect.objectContaining({
          group: NOTIFICATION_GROUP_ID,
        })
      )
    })
  })

  describe('notifyNewEmailsBatch', () => {
    it('envoie notification unique pour un seul email', async () => {
      const service = createNotificationService()

      await service.notifyNewEmailsBatch([
        {
          emailId: 'email-123',
          sender: 'client@example.com',
          subject: 'Test',
        },
      ])

      expect(mockSendNotification).toHaveBeenCalledTimes(1)
      expect(mockSendNotification).toHaveBeenCalledWith(
        expect.objectContaining({
          title: 'New message',
          body: 'client@example.com: Test',
        })
      )
    })

    it('envoie notification de groupe pour plusieurs emails', async () => {
      const service = createNotificationService()

      await service.notifyNewEmailsBatch([
        { emailId: 'email-1', sender: 'alice@example.com', subject: 'Hello' },
        { emailId: 'email-2', sender: 'bob@example.com', subject: 'Hi' },
        { emailId: 'email-3', sender: 'charlie@example.com', subject: 'Hey' },
      ])

      expect(mockSendNotification).toHaveBeenCalledTimes(1)
      expect(mockSendNotification).toHaveBeenCalledWith(
        expect.objectContaining({
          title: '3 new messages',
          body: 'From: alice@example.com, bob@example.com, charlie@example.com',
          groupSummary: true,
          group: NOTIFICATION_GROUP_ID,
        })
      )
    })

    it('tronque la liste des expediteurs si plus de 3', async () => {
      const service = createNotificationService()

      await service.notifyNewEmailsBatch([
        { emailId: 'email-1', sender: 'alice@example.com', subject: 'Hello' },
        { emailId: 'email-2', sender: 'bob@example.com', subject: 'Hi' },
        { emailId: 'email-3', sender: 'charlie@example.com', subject: 'Hey' },
        { emailId: 'email-4', sender: 'dave@example.com', subject: 'Yo' },
        { emailId: 'email-5', sender: 'eve@example.com', subject: 'Hola' },
      ])

      expect(mockSendNotification).toHaveBeenCalledWith(
        expect.objectContaining({
          title: '5 new messages',
          body: 'From: alice@example.com, bob@example.com, charlie@example.com and 2 more',
        })
      )
    })

    it('deduplique les expediteurs', async () => {
      const service = createNotificationService()

      await service.notifyNewEmailsBatch([
        { emailId: 'email-1', sender: 'alice@example.com', subject: 'Hello' },
        { emailId: 'email-2', sender: 'alice@example.com', subject: 'Hi' },
        { emailId: 'email-3', sender: 'bob@example.com', subject: 'Hey' },
      ])

      expect(mockSendNotification).toHaveBeenCalledWith(
        expect.objectContaining({
          body: 'From: alice@example.com, bob@example.com',
        })
      )
    })

    it('ne notifie pas si liste vide', async () => {
      const service = createNotificationService()

      await service.notifyNewEmailsBatch([])

      expect(mockSendNotification).not.toHaveBeenCalled()
    })

    it('ne notifie pas si desactive', async () => {
      const service = createNotificationService()
      service.setEnabled(false)

      await service.notifyNewEmailsBatch([
        { emailId: 'email-1', sender: 'alice@example.com', subject: 'Hello' },
      ])

      expect(mockSendNotification).not.toHaveBeenCalled()
    })

    it('ne notifie pas en dehors des heures de travail', async () => {
      mockShouldNotify.mockReturnValue(false)
      const service = createNotificationService()

      await service.notifyNewEmailsBatch([
        { emailId: 'email-1', sender: 'alice@example.com', subject: 'Hello' },
        { emailId: 'email-2', sender: 'bob@example.com', subject: 'Hi' },
      ])

      expect(mockSendNotification).not.toHaveBeenCalled()
    })
  })
})

describe('Window Focus on Notification Click (Story 3-7)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockIsPermissionGranted.mockResolvedValue(true)
    mockRequestPermission.mockResolvedValue('granted')
    mockOnAction.mockResolvedValue({ unregister: vi.fn() })
    mockRegisterActionTypes.mockResolvedValue(undefined)
    mockShouldNotify.mockReturnValue(true)
    resetNotificationService()
  })

  describe('AC1: Click notification opens the app', () => {
    it('notification includes emailId in extra for click handling', async () => {
      const service = createNotificationService()

      await service.notifyNewEmail({
        emailId: 'email-test-123',
        sender: 'test@example.com',
        subject: 'Test Subject',
      })

      expect(mockSendNotification).toHaveBeenCalledWith(
        expect.objectContaining({
          extra: expect.objectContaining({
            emailId: 'email-test-123',
          }),
        })
      )
    })

    it('callback receives emailId which should be used to find draft by email_id field', async () => {
      // This test documents that the notification sends emailId,
      // and App.tsx should search drafts by d.email_id === emailId (not d.id)
      const service = createNotificationService()
      const callback = vi.fn()
      let capturedHandler: ((notification: unknown) => void) | null = null

      mockOnAction.mockImplementation((cb) => {
        capturedHandler = cb
        return Promise.resolve({ unregister: vi.fn() })
      })

      await service.onNotificationClick(callback)

      // Simulate click on new_email notification
      capturedHandler!({
        notification: {
          extra: { emailId: 'email-uuid-456', type: 'new_email' },
        },
      })

      // Callback receives the emailId - App.tsx should use this to find draft.email_id
      expect(callback).toHaveBeenCalledWith('email-uuid-456')
    })
  })

  describe('AC2-AC3: Navigation to specific draft', () => {
    it('onNotificationClick callback receives the emailId', async () => {
      const service = createNotificationService()
      const clickCallback = vi.fn()
      let capturedHandler: ((notification: unknown) => void) | null = null

      mockOnAction.mockImplementation((cb) => {
        capturedHandler = cb
        return Promise.resolve({ unregister: vi.fn() })
      })

      await service.onNotificationClick(clickCallback)

      // Simulate notification click
      capturedHandler!({
        notification: {
          extra: { emailId: 'draft-abc-123', type: 'draft_ready' },
        },
      })

      expect(clickCallback).toHaveBeenCalledWith('draft-abc-123')
    })
  })

  describe('AC5: Functional when app was closed', () => {
    it('notification includes actionTypeId for OS to handle reopening', async () => {
      const service = createNotificationService()

      await service.notifyDraftReady({
        emailId: 'draft-xyz',
        sender: 'client@test.com',
        confidence: 0.9,
      })

      expect(mockSendNotification).toHaveBeenCalledWith(
        expect.objectContaining({
          actionTypeId: NOTIFICATION_ACTION_TYPE_ID,
        })
      )
    })

    it('registerNotificationActions sets up action handler for when app starts', async () => {
      const service = createNotificationService()

      await service.registerNotificationActions()

      expect(mockRegisterActionTypes).toHaveBeenCalledWith(
        expect.arrayContaining([
          expect.objectContaining({
            id: NOTIFICATION_ACTION_TYPE_ID,
            actions: expect.arrayContaining([
              expect.objectContaining({
                id: 'open',
                title: 'Open',
              }),
            ]),
          }),
        ])
      )
    })
  })
})

// TODO: update for new architecture — individual toggles removed from notification service
describe.skip('Individual Notification Type Toggles (Story 8-2)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockIsPermissionGranted.mockResolvedValue(true)
    mockRequestPermission.mockResolvedValue('granted')
    mockShouldNotify.mockReturnValue(true)
    resetNotificationService()
    clearMockLocalStorage()
  })

  describe('New Emails Toggle (AC1)', () => {
    it('ne notifie pas si toggle nouveaux emails desactive', async () => {
      mockLocalStorage['agentys_notif_new_emails'] = 'false'
      const service = createNotificationService()

      await service.notifyNewEmail({
        emailId: 'email-123',
        sender: 'client@example.com',
        subject: 'Test',
      })

      expect(mockSendNotification).not.toHaveBeenCalled()
    })

    it('notifie si toggle nouveaux emails active', async () => {
      mockLocalStorage['agentys_notif_new_emails'] = 'true'
      const service = createNotificationService()

      await service.notifyNewEmail({
        emailId: 'email-123',
        sender: 'client@example.com',
        subject: 'Test',
      })

      expect(mockSendNotification).toHaveBeenCalled()
    })

    it('notifie par defaut (toggle non defini)', async () => {
      const service = createNotificationService()

      await service.notifyNewEmail({
        emailId: 'email-123',
        sender: 'client@example.com',
        subject: 'Test',
      })

      expect(mockSendNotification).toHaveBeenCalled()
    })

    it('ne notifie pas batch si toggle nouveaux emails desactive', async () => {
      mockLocalStorage['agentys_notif_new_emails'] = 'false'
      const service = createNotificationService()

      await service.notifyNewEmailsBatch([
        { emailId: 'email-1', sender: 'alice@example.com', subject: 'Hello' },
        { emailId: 'email-2', sender: 'bob@example.com', subject: 'Hi' },
      ])

      expect(mockSendNotification).not.toHaveBeenCalled()
    })
  })

  describe('Draft Ready Toggle (AC2)', () => {
    it('ne notifie pas si toggle brouillon desactive', async () => {
      mockLocalStorage['agentys_notif_draft_ready'] = 'false'
      const service = createNotificationService()

      await service.notifyDraftReady({
        emailId: 'email-123',
        sender: 'client@example.com',
        confidence: 0.85,
      })

      expect(mockSendNotification).not.toHaveBeenCalled()
    })

    it('notifie si toggle brouillon active', async () => {
      mockLocalStorage['agentys_notif_draft_ready'] = 'true'
      const service = createNotificationService()

      await service.notifyDraftReady({
        emailId: 'email-123',
        sender: 'client@example.com',
        confidence: 0.85,
      })

      expect(mockSendNotification).toHaveBeenCalled()
    })

    it('ne notifie pas rappel si toggle brouillon desactive', async () => {
      mockLocalStorage['agentys_notif_draft_ready'] = 'false'
      const service = createNotificationService()

      await service.notifyDraftReminder({
        emailId: 'email-123',
        sender: 'client@example.com',
        draftId: 'draft-456',
      })

      expect(mockSendNotification).not.toHaveBeenCalled()
    })

    it('ne notifie pas quick reply si toggle brouillon desactive', async () => {
      mockLocalStorage['agentys_notif_draft_ready'] = 'false'
      const service = createNotificationService()

      await service.notifyDraftReadyWithQuickReply({
        emailId: 'email-123',
        draftId: 'draft-456',
        sender: 'client@example.com',
        confidence: 0.85,
        draftContent: 'Bonjour...',
      })

      expect(mockSendNotification).not.toHaveBeenCalled()
    })
  })

  describe('Sync Errors Toggle (AC3)', () => {
    it('ne notifie pas si toggle erreurs sync desactive', async () => {
      mockLocalStorage['agentys_notif_sync_errors'] = 'false'
      const service = createNotificationService()


      await (service as any).notifySyncError({
        accountName: 'test@gmail.com',
        errorMessage: 'Connexion échouée',
      })

      expect(mockSendNotification).not.toHaveBeenCalled()
    })

    it('notifie si toggle erreurs sync active', async () => {
      mockLocalStorage['agentys_notif_sync_errors'] = 'true'
      const service = createNotificationService()


      await (service as any).notifySyncError({
        accountName: 'test@gmail.com',
        errorMessage: 'Connexion échouée',
      })

      expect(mockSendNotification).toHaveBeenCalledWith(
        expect.objectContaining({
          title: 'Erreur de synchronisation',
          body: 'test@gmail.com: Connexion échouée',
        })
      )
    })

    it('notifie par defaut (toggle non defini)', async () => {
      const service = createNotificationService()


      await (service as any).notifySyncError({
        accountName: 'test@gmail.com',
        errorMessage: 'Timeout',
      })

      expect(mockSendNotification).toHaveBeenCalled()
    })

    it('ne notifie pas si master toggle desactive', async () => {
      const service = createNotificationService()
      service.setEnabled(false)


      await (service as any).notifySyncError({
        accountName: 'test@gmail.com',
        errorMessage: 'Connexion échouée',
      })

      expect(mockSendNotification).not.toHaveBeenCalled()
    })

    it('ne notifie pas en dehors des heures de travail', async () => {
      mockShouldNotify.mockReturnValue(false)
      const service = createNotificationService()


      await (service as any).notifySyncError({
        accountName: 'test@gmail.com',
        errorMessage: 'Connexion échouée',
      })

      expect(mockSendNotification).not.toHaveBeenCalled()
    })
  })
})

describe('Sound Configuration (AC3)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockIsPermissionGranted.mockResolvedValue(true)
    mockRequestPermission.mockResolvedValue('granted')
    mockShouldNotify.mockReturnValue(true)
    resetNotificationService()
    clearMockLocalStorage()
  })

  describe('getSoundSettings', () => {
    it('retourne parametres par defaut', () => {
      const service = createNotificationService()

      const settings = service.getSoundSettings()

      expect(settings.soundEnabled).toBe(true)
      expect(settings.soundName).toBe('default')
    })

    it('retourne parametres sauvegardes', () => {
      mockLocalStorage['agentys_notification_sound_enabled'] = 'false'
      mockLocalStorage['agentys_notification_sound_name'] = 'custom-sound'

      const service = createNotificationService()
      const settings = service.getSoundSettings()

      expect(settings.soundEnabled).toBe(false)
      expect(settings.soundName).toBe('custom-sound')
    })
  })

  describe('setSoundSettings', () => {
    it('sauvegarde les parametres', () => {
      const service = createNotificationService()

      service.setSoundSettings({
        soundEnabled: false,
        soundName: 'my-sound',
      })

      expect(mockLocalStorage['agentys_notification_sound_enabled']).toBe('false')
      expect(mockLocalStorage['agentys_notification_sound_name']).toBe('my-sound')
    })

    it('met a jour les notifications suivantes', async () => {
      const service = createNotificationService()

      service.setSoundSettings({
        soundEnabled: false,
        soundName: 'custom',
      })

      await service.notifyNewEmail({
        emailId: 'email-123',
        sender: 'client@example.com',
        subject: 'Test',
      })

      expect(mockSendNotification).toHaveBeenCalledWith(
        expect.objectContaining({
          silent: true,
        })
      )
    })
  })

  describe('notification avec son', () => {
    it('inclut le son si active avec son personnalise', async () => {
      mockLocalStorage['agentys_notification_sound_enabled'] = 'true'
      mockLocalStorage['agentys_notification_sound_name'] = 'Ping'

      const service = createNotificationService()

      await service.notifyNewEmail({
        emailId: 'email-123',
        sender: 'client@example.com',
        subject: 'Test',
      })

      expect(mockSendNotification).toHaveBeenCalledWith(
        expect.objectContaining({
          sound: 'Ping',
          silent: false,
        })
      )
    })

    it('utilise son systeme par defaut si default', async () => {
      mockLocalStorage['agentys_notification_sound_enabled'] = 'true'
      mockLocalStorage['agentys_notification_sound_name'] = 'default'

      const service = createNotificationService()

      await service.notifyNewEmail({
        emailId: 'email-123',
        sender: 'client@example.com',
        subject: 'Test',
      })

      expect(mockSendNotification).toHaveBeenCalledWith(
        expect.objectContaining({
          sound: undefined,
          silent: false,
        })
      )
    })

    it('est silencieux si son desactive', async () => {
      mockLocalStorage['agentys_notification_sound_enabled'] = 'false'

      const service = createNotificationService()

      await service.notifyNewEmail({
        emailId: 'email-123',
        sender: 'client@example.com',
        subject: 'Test',
      })

      expect(mockSendNotification).toHaveBeenCalledWith(
        expect.objectContaining({
          silent: true,
        })
      )
    })
  })
})

// TODO: update for new architecture — quietHours suppression moved out of notification service
describe.skip('Quiet Hours Suppression (Story 8-3)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockIsPermissionGranted.mockResolvedValue(true)
    mockRequestPermission.mockResolvedValue('granted')
    mockShouldNotify.mockReturnValue(true)
    mockShouldSuppressForQuietHours.mockReturnValue(false)
    resetNotificationService()
    clearMockLocalStorage()
  })

  describe('notifyNewEmail', () => {
    it('ne notifie pas si heures silencieuses actives', async () => {
      mockShouldSuppressForQuietHours.mockReturnValue(true)
      const service = createNotificationService()

      await service.notifyNewEmail({
        emailId: 'email-123',
        sender: 'client@example.com',
        subject: 'Test',
      })

      expect(mockSendNotification).not.toHaveBeenCalled()
    })

    it('notifie si heures silencieuses inactives', async () => {
      mockShouldSuppressForQuietHours.mockReturnValue(false)
      const service = createNotificationService()

      await service.notifyNewEmail({
        emailId: 'email-123',
        sender: 'client@example.com',
        subject: 'Test',
      })

      expect(mockSendNotification).toHaveBeenCalled()
    })
  })

  describe('notifyNewEmailsBatch', () => {
    it('ne notifie pas batch si heures silencieuses actives', async () => {
      mockShouldSuppressForQuietHours.mockReturnValue(true)
      const service = createNotificationService()

      await service.notifyNewEmailsBatch([
        { emailId: 'email-1', sender: 'alice@example.com', subject: 'Hello' },
        { emailId: 'email-2', sender: 'bob@example.com', subject: 'Hi' },
      ])

      expect(mockSendNotification).not.toHaveBeenCalled()
    })
  })

  describe('notifyDraftReady', () => {
    it('ne notifie pas brouillon si heures silencieuses actives', async () => {
      mockShouldSuppressForQuietHours.mockReturnValue(true)
      const service = createNotificationService()

      await service.notifyDraftReady({
        emailId: 'email-123',
        sender: 'client@example.com',
        confidence: 0.85,
      })

      expect(mockSendNotification).not.toHaveBeenCalled()
    })
  })

  describe('notifyDraftReminder', () => {
    it('ne notifie pas rappel si heures silencieuses actives', async () => {
      mockShouldSuppressForQuietHours.mockReturnValue(true)
      const service = createNotificationService()

      await service.notifyDraftReminder({
        emailId: 'email-123',
        sender: 'client@example.com',
        draftId: 'draft-456',
      })

      expect(mockSendNotification).not.toHaveBeenCalled()
    })
  })

  describe('notifyDraftReadyWithQuickReply', () => {
    it('ne notifie pas quick reply si heures silencieuses actives', async () => {
      mockShouldSuppressForQuietHours.mockReturnValue(true)
      const service = createNotificationService()

      await service.notifyDraftReadyWithQuickReply({
        emailId: 'email-123',
        draftId: 'draft-456',
        sender: 'client@example.com',
        confidence: 0.85,
        draftContent: 'Bonjour...',
      })

      expect(mockSendNotification).not.toHaveBeenCalled()
    })
  })

  describe('notifySyncError', () => {
    it('ne notifie pas erreur sync si heures silencieuses actives', async () => {
      mockShouldSuppressForQuietHours.mockReturnValue(true)
      const service = createNotificationService()


      await (service as any).notifySyncError({
        accountName: 'test@gmail.com',
        errorMessage: 'Connexion échouée',
      })

      expect(mockSendNotification).not.toHaveBeenCalled()
    })
  })

  describe('Focus Mode via quietHours', () => {
    it('suppression via Focus Mode est gérée par shouldSuppressForQuietHours', async () => {
      mockShouldSuppressForQuietHours.mockReturnValue(true)
      const service = createNotificationService()

      await service.notifyNewEmail({
        emailId: 'email-123',
        sender: 'client@example.com',
        subject: 'Test Focus',
      })

      expect(mockSendNotification).not.toHaveBeenCalled()
    })
  })
})
