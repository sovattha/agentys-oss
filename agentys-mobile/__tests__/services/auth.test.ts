import * as SecureStore from 'expo-secure-store';
import * as WebBrowser from 'expo-web-browser';
import * as Crypto from 'expo-crypto';
import { setToken, clearToken, subscribeAuthChange, startOAuth } from '../../src/services/auth';

beforeEach(() => {
  jest.clearAllMocks();
  jest.useRealTimers();
});

describe('subscribeAuthChange', () => {
  it('notifie les listeners quand setToken est appelé', async () => {
    const listener = jest.fn();
    const unsubscribe = subscribeAuthChange(listener);
    await setToken('new-token');
    expect(listener).toHaveBeenCalledWith(true);
    unsubscribe();
  });

  it('notifie les listeners avec false quand clearToken est appelé', async () => {
    const listener = jest.fn();
    const unsubscribe = subscribeAuthChange(listener);
    await clearToken();
    expect(listener).toHaveBeenCalledWith(false);
    unsubscribe();
  });

  it('arrête de notifier après unsubscribe', async () => {
    const listener = jest.fn();
    const unsubscribe = subscribeAuthChange(listener);
    unsubscribe();
    await clearToken();
    expect(listener).not.toHaveBeenCalled();
  });

  it('isole une exception de listener pour ne pas bloquer les autres', async () => {
    const bad = jest.fn(() => { throw new Error('boom'); });
    const good = jest.fn();
    const u1 = subscribeAuthChange(bad);
    const u2 = subscribeAuthChange(good);
    await clearToken();
    expect(good).toHaveBeenCalledWith(false);
    u1(); u2();
  });
});

describe('SecureStore I/O', () => {
  it('setToken écrit dans SecureStore', async () => {
    await setToken('abc');
    expect(SecureStore.setItemAsync).toHaveBeenCalledWith('agentys_auth_token', 'abc');
  });

  it('clearToken supprime de SecureStore', async () => {
    await clearToken();
    expect(SecureStore.deleteItemAsync).toHaveBeenCalledWith('agentys_auth_token');
  });
});

describe('startOAuth', () => {
  const bytesToHex = (bytes: number[]) =>
    bytes.map((b) => b.toString(16).padStart(2, '0')).join('');

  const stateBytes = Array.from({ length: 32 }, (_, i) => i + 1);
  const verifierBytes = Array.from({ length: 32 }, (_, i) => i + 33);
  const state = bytesToHex(stateBytes);

  const jsonResponse = (body: unknown, status = 200) => ({
    ok: status >= 200 && status < 300,
    status,
    json: jest.fn().mockResolvedValue(body),
    text: jest.fn().mockResolvedValue(JSON.stringify(body)),
  });

  it('revient au premier plan via openAuthSessionAsync puis poll la session HTTPS', async () => {
    jest.useFakeTimers();
    (Crypto.getRandomBytesAsync as jest.Mock)
      .mockResolvedValueOnce(Uint8Array.from(stateBytes))
      .mockResolvedValueOnce(Uint8Array.from(verifierBytes));
    (Crypto.digestStringAsync as jest.Mock).mockResolvedValue('challenge+/=');
    (WebBrowser.openAuthSessionAsync as jest.Mock).mockResolvedValue({
      type: 'success',
      url: `agentys://oauth-complete?success=true&state=${state}`,
    });

    const fetchMock = global.fetch as jest.Mock;
    fetchMock.mockImplementation((url: string, options?: RequestInit) => {
      if (url.endsWith('/api/oauth/config')) {
        return Promise.resolve(jsonResponse({
          gmail: {
            client_id: 'gmail-client-id',
            redirect_uri: 'https://api.agentys.io/api/oauth/gmail/callback',
            configured: true,
          },
          outlook: { client_id: 'outlook-client-id', redirect_uri: 'unused', configured: true },
        }));
      }
      if (url.endsWith('/api/oauth/pkce/store')) {
        expect(JSON.parse(String(options?.body))).toMatchObject({
          state,
          client_type: 'mobile',
        });
        return Promise.resolve(jsonResponse({ success: true }));
      }
      if (url.endsWith(`/api/oauth/session/${state}/poll`)) {
        return Promise.resolve(jsonResponse({
          status: 'success',
          email: 'mobile@gmail.com',
          token: 'agentys-jwt',
        }));
      }
      return Promise.reject(new Error(`unexpected fetch ${url}`));
    });

    const promise = startOAuth('gmail');
    await jest.advanceTimersByTimeAsync(2000);
    const result = await promise;

    expect(WebBrowser.openAuthSessionAsync).toHaveBeenCalledWith(
      expect.stringContaining('https://accounts.google.com/o/oauth2/v2/auth?'),
      'agentys://oauth-complete',
    );
    expect(result).toEqual({ success: true, email: 'mobile@gmail.com' });
    expect(SecureStore.setItemAsync).toHaveBeenCalledWith(
      'agentys_auth_token',
      'agentys-jwt',
    );
  });
});
