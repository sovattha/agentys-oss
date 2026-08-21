import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import tseslint from 'typescript-eslint'
import { defineConfig, globalIgnores } from 'eslint/config'

export default defineConfig([
  // `.yarn/releases/yarn-*.cjs` is a vendored binary, not source. Without
  // this ignore eslint flags an unused-disable directive inside it on
  // every run — pure noise that hides real warnings.
  globalIgnores(['dist', 'src-tauri', '.yarn']),
  {
    files: ['**/*.{ts,tsx}'],
    extends: [
      js.configs.recommended,
      tseslint.configs.recommended,
      reactHooks.configs.flat.recommended,
      reactRefresh.configs.vite,
    ],
    languageOptions: {
      ecmaVersion: 2020,
      globals: globals.browser,
    },
    rules: {
      // React Compiler rules (v7+) — disabled: project does not use React Compiler
      'react-hooks/refs': 'off',
      'react-hooks/set-state-in-effect': 'off',
      'react-hooks/purity': 'off',
      'react-hooks/preserve-manual-memoization': 'off',
      'react-hooks/use-memo': 'off',
      'react-hooks/immutability': 'off',
      // Disabled 2026-05-13: useState setters and refs are stable, the codebase
      // intentionally omits them from hook deps as a perf convention. The rule
      // produced 100+ warnings on otherwise-correct code, and the few real
      // missing-deps bugs it would catch are better surfaced via PR review or
      // targeted enables on a per-file basis.
      'react-hooks/exhaustive-deps': 'off',
      // Ignore intentionally unused vars prefixed with _
      '@typescript-eslint/no-unused-vars': ['error', {
        varsIgnorePattern: '^_',
        argsIgnorePattern: '^_',
        caughtErrorsIgnorePattern: '^_',
        destructuredArrayIgnorePattern: '^_',
      }],
    },
  },
  // Test files can legitimately use `any` for mocks, and may export helpers
  // alongside test cases (react-refresh false positive).
  {
    files: [
      '**/__tests__/**/*.{ts,tsx}',
      '**/*.test.{ts,tsx}',
      '**/*.spec.{ts,tsx}',
    ],
    rules: {
      '@typescript-eslint/no-explicit-any': 'off',
      'react-refresh/only-export-components': 'off',
    },
  },
])
