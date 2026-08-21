/**
 * Garde d'authentification — redirige vers login si non authentifié.
 */

import { useEffect } from "react";
import { useRouter } from "expo-router";
import { useAuth } from "../hooks/useAuth";
import { View } from "react-native";
import { theme } from "../theme";
import { BreathingTriangle } from "./BreathingTriangle";

export function AuthGuard({ children }: { children: React.ReactNode }) {
  const { isAuthenticated, isLoading } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!isLoading && !isAuthenticated) {
      router.replace("/login");
    }
  }, [isAuthenticated, isLoading]);

  if (isLoading) {
    return (
      <View style={{ flex: 1, justifyContent: "center", alignItems: "center", backgroundColor: theme.colors.bg }}>
        <BreathingTriangle size={120} mode="loading" />
      </View>
    );
  }

  if (!isAuthenticated) return null;

  return <>{children}</>;
}
