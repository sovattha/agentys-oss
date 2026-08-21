module.exports = {
  preset: 'jest-expo',
  setupFiles: ['./jest.setup.js'],
  transformIgnorePatterns: [
    'node_modules/(?!((jest-)?react-native|@react-native(-community)?)|expo(nent)?|@expo(nent)?/.*|react-navigation|@react-navigation/.*|socket.io-client|react-native-webview)',
  ],
  testPathIgnorePatterns: [
    '/node_modules/',
    '/__tests__/support/',
  ],
  collectCoverage: false,
  // Ratchet (#1128) : plancher = niveau atteint au 2026-07-02, arrondi à
  // l'inférieur. Ne JAMAIS baisser — remonter au fil des nouveaux tests.
  // Cible projet : 80 %.
  coverageThreshold: {
    global: {
      statements: 37,
      branches: 26,
      functions: 36,
      lines: 39,
    },
  },
  coverageDirectory: 'coverage',
  coverageReporters: ['text', 'lcov'],
  collectCoverageFrom: [
    '<rootDir>/src/**/*.{ts,tsx}',
    '<rootDir>/app/**/*.{ts,tsx}',
    '!<rootDir>/src/**/*.d.ts',
  ],
};
