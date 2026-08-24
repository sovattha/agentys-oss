/*
 * Agentys — voice-first email assistant.
 * Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
 *
 * This program is free software: you can redistribute it and/or modify it
 * under the terms of the GNU Affero General Public License as published by
 * the Free Software Foundation, either version 3 of the License, or (at your
 * option) any later version. See the LICENSE file for details.
 *
 * SPDX-License-Identifier: AGPL-3.0-or-later
 */

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
