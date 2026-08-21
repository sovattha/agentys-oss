import React from 'react';
import { render } from '@testing-library/react-native';
import { AuthContext } from '../../src/hooks/useAuth';

interface AuthContextValue {
  isAuthenticated: boolean;
  isLoading: boolean;
  login: (token: string) => Promise<void>;
  logout: () => Promise<void>;
}

const defaultAuth: AuthContextValue = {
  isAuthenticated: true,
  isLoading: false,
  login: jest.fn().mockResolvedValue(undefined),
  logout: jest.fn().mockResolvedValue(undefined),
};

export function renderWithProviders(
  ui: React.ReactElement,
  authOverrides: Partial<AuthContextValue> = {}
) {
  const authValue = { ...defaultAuth, ...authOverrides };
  return render(
    <AuthContext.Provider value={authValue}>{ui}</AuthContext.Provider>
  );
}
