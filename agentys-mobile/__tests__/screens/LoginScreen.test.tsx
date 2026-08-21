import React from 'react';
import { render, fireEvent, waitFor, act } from '@testing-library/react-native';
import { Alert } from 'react-native';
import LoginScreen from '../../app/login';

const mockReplace = jest.fn();
const mockStartOAuth = jest.fn();

jest.mock('expo-router', () => ({
  useRouter: () => ({ replace: mockReplace }),
}));

jest.mock('../../src/services/auth', () => ({
  startOAuth: (...args: any[]) => mockStartOAuth(...args),
}));

jest.mock('../../src/hooks/useMicLevel', () => ({
  useMicLevel: () => null,
}));

jest.mock('../../src/components/BreathingTriangle', () => ({
  BreathingTriangle: () => null,
}));

beforeEach(() => {
  jest.clearAllMocks();
});

describe('LoginScreen', () => {
  it('affiche les boutons Gmail et Outlook', () => {
    const { getByLabelText } = render(<LoginScreen />);
    expect(getByLabelText('Se connecter avec Gmail')).toBeTruthy();
    expect(getByLabelText('Se connecter avec Outlook')).toBeTruthy();
  });

  it('déclenche OAuth Gmail au press', async () => {
    mockStartOAuth.mockResolvedValue({ success: true });
    const { getByLabelText } = render(<LoginScreen />);
    await act(async () => {
      fireEvent.press(getByLabelText('Se connecter avec Gmail'));
    });
    await waitFor(() => {
      expect(mockStartOAuth).toHaveBeenCalledWith('gmail');
    });
  });

  it('déclenche OAuth Outlook au press', async () => {
    mockStartOAuth.mockResolvedValue({ success: true });
    const { getByLabelText } = render(<LoginScreen />);
    await act(async () => {
      fireEvent.press(getByLabelText('Se connecter avec Outlook'));
    });
    await waitFor(() => {
      expect(mockStartOAuth).toHaveBeenCalledWith('outlook');
    });
  });

  it('redirige vers / après OAuth réussi', async () => {
    mockStartOAuth.mockResolvedValue({ success: true });
    const { getByLabelText } = render(<LoginScreen />);
    await act(async () => {
      fireEvent.press(getByLabelText('Se connecter avec Gmail'));
    });
    await waitFor(() => {
      expect(mockReplace).toHaveBeenCalledWith('/');
    });
  });

  it('ne redirige pas si success=false', async () => {
    mockStartOAuth.mockResolvedValue({ success: false });
    const { getByLabelText } = render(<LoginScreen />);
    await act(async () => {
      fireEvent.press(getByLabelText('Se connecter avec Outlook'));
    });
    await waitFor(() => {
      expect(mockStartOAuth).toHaveBeenCalled();
    });
    expect(mockReplace).not.toHaveBeenCalled();
  });

  it('affiche erreur si OAuth échoue', async () => {
    jest.spyOn(Alert, 'alert').mockImplementation(() => {});
    mockStartOAuth.mockRejectedValueOnce(new Error('Réseau HS'));
    const { getByLabelText } = render(<LoginScreen />);
    await act(async () => {
      fireEvent.press(getByLabelText('Se connecter avec Gmail'));
    });
    await waitFor(() => {
      expect(Alert.alert).toHaveBeenCalledWith('Erreur', 'Réseau HS');
    });
  });
});
