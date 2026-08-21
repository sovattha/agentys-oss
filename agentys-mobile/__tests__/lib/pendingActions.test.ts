/**
 * PendingActionManager — le cœur du « agis d'abord, annule si besoin ».
 * Contrats : exécution différée, annulation dans la fenêtre, flush immédiat
 * en fin de session, journal de crash rejoué au boot.
 */
import {
  PendingActionManager,
  flushJournal,
} from '../../src/lib/pendingActions';
import * as SecureStore from 'expo-secure-store';

const mockGetItem = SecureStore.getItemAsync as jest.Mock;
const mockSetItem = SecureStore.setItemAsync as jest.Mock;

describe('PendingActionManager', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    jest.useFakeTimers();
  });

  afterEach(() => {
    jest.useRealTimers();
  });

  it("n'exécute PAS avant le délai", () => {
    const manager = new PendingActionManager();
    const execute = jest.fn().mockResolvedValue(undefined);
    manager.schedule('archive', 'email-1', 5000, execute);
    jest.advanceTimersByTime(4999);
    expect(execute).not.toHaveBeenCalled();
    expect(manager.count()).toBe(1);
  });

  it('exécute après le délai', async () => {
    const manager = new PendingActionManager();
    const execute = jest.fn().mockResolvedValue(undefined);
    manager.schedule('archive', 'email-1', 5000, execute);
    jest.advanceTimersByTime(5000);
    expect(execute).toHaveBeenCalledTimes(1);
    expect(manager.count()).toBe(0);
  });

  it('cancelLast annule la PLUS RÉCENTE action', () => {
    const manager = new PendingActionManager();
    const exec1 = jest.fn().mockResolvedValue(undefined);
    const exec2 = jest.fn().mockResolvedValue(undefined);
    manager.schedule('archive', 'email-1', 5000, exec1);
    jest.advanceTimersByTime(10); // sépare les createdAt
    manager.schedule('send', 'draft-2', 8000, exec2);

    const cancelled = manager.cancelLast();
    expect(cancelled?.kind).toBe('send');
    expect(cancelled?.targetId).toBe('draft-2');

    jest.advanceTimersByTime(20_000);
    expect(exec2).not.toHaveBeenCalled(); // annulé
    expect(exec1).toHaveBeenCalledTimes(1); // pas touché
  });

  it('cancelLast(kind) filtre par type', () => {
    const manager = new PendingActionManager();
    const execArchive = jest.fn().mockResolvedValue(undefined);
    const execSend = jest.fn().mockResolvedValue(undefined);
    manager.schedule('archive', 'email-1', 5000, execArchive);
    jest.advanceTimersByTime(10);
    manager.schedule('send', 'draft-1', 8000, execSend);

    // Annule l'ARCHIVE spécifiquement, pas le send (plus récent)
    const cancelled = manager.cancelLast('archive');
    expect(cancelled?.kind).toBe('archive');

    jest.advanceTimersByTime(20_000);
    expect(execArchive).not.toHaveBeenCalled();
    expect(execSend).toHaveBeenCalledTimes(1);
  });

  it('cancelLast sans action en attente → null', () => {
    const manager = new PendingActionManager();
    expect(manager.cancelLast()).toBeNull();
  });

  it("onError est appelé quand l'exécution échoue", async () => {
    const manager = new PendingActionManager();
    const onError = jest.fn();
    manager.schedule('send', 'draft-1', 1000,
      jest.fn().mockRejectedValue(new Error('Backend 500')),
      onError,
    );
    jest.advanceTimersByTime(1000);
    // Laisse la promesse rejetée se propager
    await jest.runAllTimersAsync();
    expect(onError).toHaveBeenCalledWith(expect.any(Error));
  });

  it('flushAll exécute tout immédiatement (fin de session)', async () => {
    const manager = new PendingActionManager();
    const exec1 = jest.fn().mockResolvedValue(undefined);
    const exec2 = jest.fn().mockResolvedValue(undefined);
    manager.schedule('archive', 'email-1', 60_000, exec1);
    manager.schedule('send', 'draft-1', 60_000, exec2);

    await manager.flushAll();
    expect(exec1).toHaveBeenCalledTimes(1);
    expect(exec2).toHaveBeenCalledTimes(1);
    expect(manager.count()).toBe(0);

    // Les timers annulés ne re-exécutent pas
    jest.advanceTimersByTime(120_000);
    expect(exec1).toHaveBeenCalledTimes(1);
    expect(exec2).toHaveBeenCalledTimes(1);
  });

  it('count(kind) compte par type', () => {
    const manager = new PendingActionManager();
    manager.schedule('archive', 'e1', 5000, jest.fn().mockResolvedValue(undefined));
    manager.schedule('archive', 'e2', 5000, jest.fn().mockResolvedValue(undefined));
    manager.schedule('send', 'd1', 8000, jest.fn().mockResolvedValue(undefined));
    expect(manager.count()).toBe(3);
    expect(manager.count('archive')).toBe(2);
    expect(manager.count('send')).toBe(1);
    expect(manager.count('delete')).toBe(0);
  });

  it('onChange notifie le compteur sur schedule / cancel / exécution (chip undo)', () => {
    const manager = new PendingActionManager();
    const counts: number[] = [];
    manager.setOnChange((c) => counts.push(c));

    manager.schedule('archive', 'e1', 5000, jest.fn().mockResolvedValue(undefined));
    jest.advanceTimersByTime(10); // sépare les createdAt pour un cancelLast déterministe
    manager.schedule('send', 'd1', 8000, jest.fn().mockResolvedValue(undefined));
    manager.cancelLast(); // annule le send (le plus récent) → 1
    expect(counts).toEqual([1, 2, 1]);

    jest.advanceTimersByTime(5000); // l'archive s'exécute → 0
    expect(counts[counts.length - 1]).toBe(0);
  });
});

describe('flushJournal (filet de crash)', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  const executors = () => ({
    archive: jest.fn().mockResolvedValue(undefined),
    delete: jest.fn().mockResolvedValue(undefined),
    send: jest.fn().mockResolvedValue(undefined),
  });

  it('journal vide → rien', async () => {
    mockGetItem.mockResolvedValueOnce(null);
    const ex = executors();
    const result = await flushJournal(ex);
    expect(result).toEqual({ executed: 0, dropped: 0 });
    expect(ex.send).not.toHaveBeenCalled();
  });

  it('rejoue les actions orphelines par kind', async () => {
    mockGetItem.mockResolvedValueOnce(JSON.stringify([
      { id: '1', kind: 'send', targetId: 'draft-9', createdAt: Date.now() - 1000 },
      { id: '2', kind: 'archive', targetId: 'email-3', createdAt: Date.now() - 1000 },
    ]));
    const ex = executors();
    const result = await flushJournal(ex);
    expect(ex.send).toHaveBeenCalledWith('draft-9');
    expect(ex.archive).toHaveBeenCalledWith('email-3');
    expect(result.executed).toBe(2);
  });

  it('les entrées trop vieilles (> 24 h) sont jetées, pas exécutées', async () => {
    mockGetItem.mockResolvedValueOnce(JSON.stringify([
      { id: '1', kind: 'send', targetId: 'draft-old', createdAt: Date.now() - 48 * 3600 * 1000 },
    ]));
    const ex = executors();
    const result = await flushJournal(ex);
    expect(ex.send).not.toHaveBeenCalled();
    expect(result.dropped).toBe(1);
  });

  it("un refus API (déjà envoyé) n'arrête pas le flush des autres", async () => {
    mockGetItem.mockResolvedValueOnce(JSON.stringify([
      { id: '1', kind: 'send', targetId: 'draft-dup', createdAt: Date.now() - 1000 },
      { id: '2', kind: 'archive', targetId: 'email-ok', createdAt: Date.now() - 1000 },
    ]));
    const ex = executors();
    ex.send.mockRejectedValueOnce(new Error('409 already sent'));
    const result = await flushJournal(ex);
    expect(ex.archive).toHaveBeenCalledWith('email-ok');
    expect(result.executed).toBe(1);
    expect(result.dropped).toBe(1);
  });
});
