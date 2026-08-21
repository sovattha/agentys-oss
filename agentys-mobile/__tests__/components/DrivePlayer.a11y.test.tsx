/**
 * F12 (LOW) — accessibility regression guard for DrivePlayer.
 *
 * The recent DrivePlayer UI cleanup removed the central AgentysLogo and
 * its long-press-to-settings shortcut. VoiceOver users now reach settings
 * via: back-button (exits drive) → home → long-press triangle.
 *
 * This test pins the back button's accessibility surface so the path is
 * never silently regressed: it must have a `role=button`, a label, and a
 * hint that documents the exit-then-long-press route.
 */
import React from 'react';
import { render } from '@testing-library/react-native';
import { DrivePlayer } from '../../src/components/DrivePlayer';

const defaultProps = {
  onNext: jest.fn(),
};

describe('DrivePlayer — F12 a11y settings reachability', () => {
  beforeEach(() => jest.clearAllMocks());

  it('back button surfaces label + hint when onBack is provided', () => {
    const { getByLabelText } = render(
      <DrivePlayer
        {...defaultProps}
        state="choosing"
        onBack={jest.fn()}
        senderName="Marie"
        emailSubject="Sujet"
      />,
    );
    // The label describes the primary action (back to prev email).
    const backBtn = getByLabelText("Retour à l'email précédent");
    expect(backBtn).toBeTruthy();
    // The hint explains how to reach settings — load-bearing for blind drivers.
    const hint = backBtn.props.accessibilityHint;
    expect(typeof hint).toBe('string');
    expect(hint).toMatch(/réglages/i);
    expect(hint).toMatch(/triangle|accueil|long-press/i);
    // Role MUST be button (Pressable role hint for screen readers).
    expect(backBtn.props.accessibilityRole).toBe('button');
  });

  it('does NOT render the long-press settings shortcut anymore (regression guard)', () => {
    const { queryByLabelText } = render(
      <DrivePlayer
        {...defaultProps}
        state="choosing"
        onBack={jest.fn()}
      />,
    );
    // Old label was "Maintenir pour les réglages". MUST NOT come back here —
    // settings access goes through home now.
    expect(queryByLabelText('Maintenir pour les réglages')).toBeNull();
    expect(queryByLabelText(/Hold for settings/i)).toBeNull();
  });
});
