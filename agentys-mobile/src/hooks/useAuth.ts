/**
 * Hook d'authentification avec contexte React.
 */

import { createContext, useContext, useEffect, useState, useCallback } from "react";
import { getToken, clearToken, setToken, subscribeAuthChange } from "../services/auth";

interface AuthState {
  isAuthenticated: boolean;
  isLoading: boolean;
  login: (token: string) => Promise<void>;
  logout: () => Promise<void>;
}

export const AuthContext = createContext<AuthState>({
  isAuthenticated: false,
  isLoading: true,
  login: async () => {},
  logout: async () => {},
});

export function useAuthProvider(): AuthState {
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    getToken().then((token) => {
      setIsAuthenticated(!!token);
      setIsLoading(false);
    });
    // React to token invalidation triggered by API 401 (clearToken in apiFetch)
    return subscribeAuthChange((hasToken) => setIsAuthenticated(hasToken));
  }, []);

  const login = useCallback(async (token: string) => {
    await setToken(token);
    setIsAuthenticated(true);
  }, []);

  const logout = useCallback(async () => {
    await clearToken();
    setIsAuthenticated(false);
  }, []);

  return { isAuthenticated, isLoading, login, logout };
}

export function useAuth(): AuthState {
  return useContext(AuthContext);
}
