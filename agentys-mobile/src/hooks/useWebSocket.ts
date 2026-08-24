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
 * Hook WebSocket — écoute les événements temps réel du backend.
 * Consomme le namespace /daemon via socket.io-client.
 */

import { useEffect, useState, useRef, useCallback } from "react";
import type { Socket } from "socket.io-client";
import { connectSocket, disconnectSocket } from "../services/websocket";

interface DaemonEvent {
  type: string;
  email_id?: string;
  draft_id?: string;
  sender?: string;
  subject?: string;
  [key: string]: unknown;
}

interface UseWebSocketOptions {
  enabled?: boolean;
  onNewEmail?: (event: DaemonEvent) => void;
  onDraftReady?: (event: DaemonEvent) => void;
  onEmailArchived?: (event: DaemonEvent) => void;
}

interface UseWebSocketResult {
  isConnected: boolean;
  lastEvent: DaemonEvent | null;
}

export function useWebSocket(options: UseWebSocketOptions = {}): UseWebSocketResult {
  const { enabled = true, onNewEmail, onDraftReady, onEmailArchived } = options;
  const [isConnected, setIsConnected] = useState(false);
  const [lastEvent, setLastEvent] = useState<DaemonEvent | null>(null);
  const socketRef = useRef<Socket | null>(null);

  // Keep callbacks fresh via refs
  const onNewEmailRef = useRef(onNewEmail);
  const onDraftReadyRef = useRef(onDraftReady);
  const onEmailArchivedRef = useRef(onEmailArchived);
  onNewEmailRef.current = onNewEmail;
  onDraftReadyRef.current = onDraftReady;
  onEmailArchivedRef.current = onEmailArchived;

  const handleEvent = useCallback((data: DaemonEvent) => {
    setLastEvent(data);
    switch (data.type) {
      case "email_received":
      case "new_email":
        onNewEmailRef.current?.(data);
        break;
      case "draft_ready":
      case "draft_complete":
        onDraftReadyRef.current?.(data);
        break;
      case "email_archived":
        onEmailArchivedRef.current?.(data);
        break;
    }
  }, []);

  useEffect(() => {
    if (!enabled) return;

    let mounted = true;

    (async () => {
      try {
        const sock = await connectSocket();
        if (!mounted) return;
        socketRef.current = sock;
        setIsConnected(sock.connected);

        sock.on("connect", () => mounted && setIsConnected(true));
        sock.on("disconnect", () => mounted && setIsConnected(false));
        sock.on("daemon_event", (data: DaemonEvent) => mounted && handleEvent(data));
      } catch {
        // Connection failed — will retry via socket.io reconnection
      }
    })();

    return () => {
      mounted = false;
      disconnectSocket();
      setIsConnected(false);
    };
  }, [enabled, handleEvent]);

  return { isConnected, lastEvent };
}
