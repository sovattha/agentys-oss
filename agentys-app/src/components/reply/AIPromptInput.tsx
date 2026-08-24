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

import { useState, useRef, useEffect, useCallback } from 'react';
import './AIPromptInput.css';

interface AIPromptInputProps {
  onSubmit: (prompt: string) => void;
  onCancel: () => void;
  isLoading?: boolean;
  error?: string | null;
  placeholder?: string;
}

const QUICK_SUGGESTIONS = [
  'Reply politely',
  'Decline politely',
  'Ask for more details',
  'Confirm receipt',
];

export function AIPromptInput({
  onSubmit,
  onCancel,
  isLoading = false,
  error = null,
  placeholder = 'Ask Agentys',
}: AIPromptInputProps) {
  const [prompt, setPrompt] = useState('');
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    // Focus input on mount
    inputRef.current?.focus();
  }, []);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLInputElement>) => {
      if (e.key === 'Enter' && !e.shiftKey && prompt.trim()) {
        e.preventDefault();
        onSubmit(prompt.trim());
      } else if (e.key === 'Escape') {
        e.preventDefault();
        onCancel();
      }
    },
    [prompt, onSubmit, onCancel]
  );

  const handleSubmit = useCallback(() => {
    if (prompt.trim() && !isLoading) {
      onSubmit(prompt.trim());
    }
  }, [prompt, isLoading, onSubmit]);

  const handleSuggestionClick = useCallback(
    (suggestion: string) => {
      if (!isLoading) {
        onSubmit(suggestion);
      }
    },
    [isLoading, onSubmit]
  );

  return (
    <div className="ai-prompt-container" data-testid="ai-prompt-container">
      <div className="ai-prompt-header">
        <span className="ai-prompt-icon">✨</span>
        <span>Write with Agentys AI</span>
        <span className="ai-prompt-hint">
          <kbd>Enter</kbd> to submit, <kbd>Esc</kbd> to cancel
        </span>
      </div>

      <div className="ai-prompt-input-wrapper">
        <input
          ref={inputRef}
          type="text"
          className="ai-prompt-input"
          data-testid="ai-prompt-input"
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={placeholder}
          disabled={isLoading}
          autoComplete="off"
        />
        <button
          type="button"
          className="ai-prompt-submit"
          data-testid="ai-prompt-submit"
          onClick={handleSubmit}
          disabled={!prompt.trim() || isLoading}
        >
          Generate
        </button>
      </div>

      {isLoading && (
        <div className="ai-prompt-loading" data-testid="ai-prompt-loading">
          <span className="ai-prompt-spinner" />
          <span>Generating response...</span>
        </div>
      )}

      {error && (
        <div className="ai-prompt-error" data-testid="ai-prompt-error">
          <span className="ai-prompt-error-icon">!</span>
          <span>{error}</span>
        </div>
      )}

      {!isLoading && !error && (
        <div className="ai-prompt-suggestions">
          {QUICK_SUGGESTIONS.map((suggestion) => (
            <button
              key={suggestion}
              type="button"
              className="ai-suggestion-chip"
              data-testid="ai-suggestion-chip"
              onClick={() => handleSuggestionClick(suggestion)}
            >
              {suggestion}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
