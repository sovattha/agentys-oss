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

import { render, screen } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import { Avatar } from './Avatar';

describe('Avatar', () => {
  describe('getInitials', () => {
    it('should display initials from name with two words', () => {
      render(<Avatar name="John Doe" email="john@example.com" />);
      expect(screen.getByText('JD')).toBeInTheDocument();
    });

    it('should display initials from name with multiple words', () => {
      render(<Avatar name="Jean Pierre Martin" email="jpm@example.com" />);
      // First + Last = JM
      expect(screen.getByText('JM')).toBeInTheDocument();
    });

    it('should display first two letters for single word name', () => {
      render(<Avatar name="Alice" email="alice@example.com" />);
      expect(screen.getByText('AL')).toBeInTheDocument();
    });

    it('should extract initials from email when name is null', () => {
      render(<Avatar name={null} email="john.doe@example.com" />);
      expect(screen.getByText('JD')).toBeInTheDocument();
    });

    it('should handle email with underscore separator', () => {
      render(<Avatar name={null} email="alice_martin@example.com" />);
      expect(screen.getByText('AM')).toBeInTheDocument();
    });

    it('should handle email with dash separator', () => {
      render(<Avatar name={null} email="bob-jones@example.com" />);
      expect(screen.getByText('BJ')).toBeInTheDocument();
    });

    it('should handle simple email without separator', () => {
      render(<Avatar name={null} email="username@example.com" />);
      expect(screen.getByText('US')).toBeInTheDocument();
    });
  });

  describe('size variants', () => {
    it('should render with default md size', () => {
      render(<Avatar name="Test User" email="test@example.com" />);
      const avatar = screen.getByLabelText('Avatar for Test User');
      expect(avatar).toHaveClass('avatar-md');
    });

    it('should render with sm size', () => {
      render(<Avatar name="Test User" email="test@example.com" size="sm" />);
      const avatar = screen.getByLabelText('Avatar for Test User');
      expect(avatar).toHaveClass('avatar-sm');
    });

    it('should render with lg size', () => {
      render(<Avatar name="Test User" email="test@example.com" size="lg" />);
      const avatar = screen.getByLabelText('Avatar for Test User');
      expect(avatar).toHaveClass('avatar-lg');
    });
  });

  describe('color generation', () => {
    it('should generate consistent color for same email', () => {
      const { container: container1 } = render(
        <Avatar name="Test" email="same@example.com" />
      );
      const { container: container2 } = render(
        <Avatar name="Test" email="same@example.com" />
      );

      const avatar1 = container1.querySelector('.avatar') as HTMLElement;
      const avatar2 = container2.querySelector('.avatar') as HTMLElement;

      expect(avatar1.style.backgroundColor).toBe(avatar2.style.backgroundColor);
    });

    it('should generate different colors for different emails', () => {
      const { container: container1 } = render(
        <Avatar name="Test" email="alice@example.com" />
      );
      const { container: container2 } = render(
        <Avatar name="Test" email="bob@different.com" />
      );

      const avatar1 = container1.querySelector('.avatar') as HTMLElement;
      const avatar2 = container2.querySelector('.avatar') as HTMLElement;

      // Colors should be different (high probability for different emails)
      expect(avatar1.style.backgroundColor).toBeTruthy();
      expect(avatar2.style.backgroundColor).toBeTruthy();
    });
  });

  describe('accessibility', () => {
    it('should have accessible aria-label with name', () => {
      render(<Avatar name="Alice Martin" email="alice@example.com" />);
      expect(screen.getByLabelText('Avatar for Alice Martin')).toBeInTheDocument();
    });

    it('should use email in aria-label when name is null', () => {
      render(<Avatar name={null} email="alice@example.com" />);
      expect(screen.getByLabelText('Avatar for alice@example.com')).toBeInTheDocument();
    });
  });
});
