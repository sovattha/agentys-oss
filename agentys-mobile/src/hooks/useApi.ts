/**
 * Hook API avec gestion d'erreurs et état de chargement.
 */

import { useState, useCallback } from "react";
import { useAuth } from "./useAuth";

interface ApiState<T> {
  data: T | null;
  error: string | null;
  loading: boolean;
  execute: (...args: any[]) => Promise<T | null>;
}

export function useApi<T>(apiFunction: (...args: any[]) => Promise<T>): ApiState<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const { logout } = useAuth();

  const execute = useCallback(
    async (...args: any[]): Promise<T | null> => {
      setLoading(true);
      setError(null);
      try {
        const result = await apiFunction(...args);
        setData(result);
        return result;
      } catch (err: any) {
        if (err.message === "Unauthorized") {
          await logout();
        }
        setError(err.message || "An error occurred");
        return null;
      } finally {
        setLoading(false);
      }
    },
    [apiFunction, logout]
  );

  return { data, error, loading, execute };
}
