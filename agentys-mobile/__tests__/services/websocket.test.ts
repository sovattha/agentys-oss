/**
 * Tests du singleton WebSocket (issue #1120) :
 *  - une seule instance io() même sous appels concurrents / socket déconnecté
 *  - token frais via la forme fonction de `auth`
 *  - reconnexion illimitée (pas de reconnectionAttempts)
 *  - réaction aux changements d'auth (logout → disconnect, re-login → reconnect)
 */

type AuthListener = (hasToken: boolean) => void;

const mockGetToken = jest.fn<Promise<string | null>, []>();
let authListener: AuthListener | null = null;

jest.mock("../../src/services/auth", () => ({
  getToken: (...args: []) => mockGetToken(...args),
  subscribeAuthChange: (fn: AuthListener) => {
    authListener = fn;
    return () => {
      authListener = null;
    };
  },
}));

interface IoOpts {
  auth: (cb: (data: { token: string | null }) => void) => void;
  reconnection: boolean;
  reconnectionAttempts?: number;
  reconnectionDelayMax: number;
}

const mockConnect = jest.fn();
const mockDisconnect = jest.fn(() => ({ connect: mockConnect }));
const fakeSocket = {
  connected: false,
  on: jest.fn(),
  off: jest.fn(),
  connect: mockConnect,
  disconnect: mockDisconnect,
};
const mockIo = jest.fn((_url: string, _opts: IoOpts) => fakeSocket);

jest.mock("socket.io-client", () => ({
  io: (url: string, opts: IoOpts) => mockIo(url, opts),
}));

// Import frais à chaque test : le module garde un état singleton.
// NB : require() synchrone — l'import dynamique casse sous ce Jest
// (--experimental-vm-modules absent, même leçon que api.ts:213).
function loadModule(): typeof import("../../src/services/websocket") {
  let mod: typeof import("../../src/services/websocket") | undefined;
  jest.isolateModules(() => {
    mod = require("../../src/services/websocket");
  });
  return mod!;
}

beforeEach(() => {
  jest.clearAllMocks();
  authListener = null;
  mockGetToken.mockResolvedValue("jwt-fresh");
});

describe("connectSocket — singleton strict", () => {
  it("crée une seule instance sous appels concurrents", async () => {
    const { connectSocket } = await loadModule();

    const [a, b] = await Promise.all([connectSocket(), connectSocket()]);

    expect(mockIo).toHaveBeenCalledTimes(1);
    expect(a).toBe(b);
  });

  it("réutilise un socket existant même déconnecté (Socket.IO gère la reconnexion)", async () => {
    const { connectSocket } = await loadModule();

    const first = await connectSocket();
    fakeSocket.connected = false;
    const second = await connectSocket();

    expect(mockIo).toHaveBeenCalledTimes(1);
    expect(second).toBe(first);
  });

  it("configure une reconnexion illimitée avec backoff plafonné", async () => {
    const { connectSocket } = await loadModule();
    await connectSocket();

    const opts = mockIo.mock.calls[0][1];
    expect(opts.reconnection).toBe(true);
    expect(opts.reconnectionAttempts).toBeUndefined();
    expect(opts.reconnectionDelayMax).toBe(15_000);
  });
});

describe("connectSocket — token frais", () => {
  it("fournit le token courant via la fonction auth à chaque appel", async () => {
    const { connectSocket } = await loadModule();
    await connectSocket();

    const opts = mockIo.mock.calls[0][1] as {
      auth: (cb: (data: { token: string | null }) => void) => void;
    };

    // La fonction auth résout aussi account_id via fetch(/api/accounts) —
    // on flush toutes les microtasks (plusieurs await en chaîne).
    const flush = () => new Promise((r) => setImmediate(r));

    mockGetToken.mockResolvedValueOnce("jwt-1");
    const cb1 = jest.fn();
    opts.auth(cb1);
    await flush();
    expect(cb1).toHaveBeenCalledWith(expect.objectContaining({ token: "jwt-1" }));

    mockGetToken.mockResolvedValueOnce("jwt-2");
    const cb2 = jest.fn();
    opts.auth(cb2);
    await flush();
    expect(cb2).toHaveBeenCalledWith(expect.objectContaining({ token: "jwt-2" }));
  });

  it("envoie token null si getToken échoue (le backend rejette proprement)", async () => {
    const { connectSocket } = await loadModule();
    await connectSocket();

    const opts = mockIo.mock.calls[0][1] as {
      auth: (cb: (data: { token: string | null }) => void) => void;
    };
    mockGetToken.mockRejectedValueOnce(new Error("securestore down"));
    const cb = jest.fn();
    opts.auth(cb);
    await Promise.resolve();
    await Promise.resolve();
    expect(cb).toHaveBeenCalledWith({ token: null });
  });
});

describe("réaction aux changements d'auth", () => {
  it("logout → socket fermé et purgé", async () => {
    const { connectSocket, getSocket } = await loadModule();
    await connectSocket();

    authListener!(false);

    expect(mockDisconnect).toHaveBeenCalledTimes(1);
    expect(getSocket()).toBeNull();
  });

  it("re-login avec socket existant → disconnect().connect() pour réévaluer auth", async () => {
    const { connectSocket, getSocket } = await loadModule();
    await connectSocket();

    authListener!(true);

    expect(mockDisconnect).toHaveBeenCalledTimes(1);
    expect(mockConnect).toHaveBeenCalledTimes(1);
    expect(getSocket()).not.toBeNull();
  });

  it("login sans socket existant → no-op (connexion différée au prochain connectSocket)", async () => {
    await loadModule();

    authListener!(true);

    expect(mockIo).not.toHaveBeenCalled();
    expect(mockDisconnect).not.toHaveBeenCalled();
  });
});
