import path from 'node:path';
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vitest/config';

export default defineConfig({
  resolve: {
    alias: { '@': path.resolve(__dirname, '.') },
  },
  // Next.js compiles JSX with the automatic runtime and its tsconfig sets
  // `jsx: preserve` (Next does the transform itself). Vitest would otherwise
  // inherit `preserve` and fail to parse every .tsx file, so the React plugin
  // owns the JSX transform for the test run. It replaces the old top-level
  // `esbuild: { jsx: 'automatic' }` shortcut, which Vite 8 silently ignores now
  // that Oxc (not esbuild) is the transform pipeline.
  plugins: [react()],
  test: {
    environment: 'jsdom',
    setupFiles: ['./tests/setup.ts'],
    globals: true,
    include: ['tests/**/*.test.{ts,tsx}'],
    coverage: {
      provider: 'v8',
      reporter: ['text', 'lcov', 'json-summary'],
      // The route pages under app/ are verified by the render smoke tests in
      // tests/pages.test.ts and by `npm run build`; measuring them here would
      // drown the signal. The floors below cover the unit-tested modules.
      // Vitest 4 always reports every file matched by `include`, even when
      // nothing imported it (that replaced the old `coverage.all` flag), so a
      // newly added, untested module still shows up at 0% and pulls the floor
      // down - which is the point: new code arrives with its tests.
      include: [
        'components/**/*.{ts,tsx}',
        'hooks/**/*.{ts,tsx}',
        'lib/**/*.{ts,tsx}',
        'services/**/*.ts',
      ],
      thresholds: {
        // Floors over lib/, hooks/, services/ and components/ (the modules that
        // carry logic). With `all: true`, adding an untested module lowers the
        // number and fails the build - that is the point: new code arrives with
        // its tests. Raised to 80% per DataFactor quality recommendation.
        lines: 80,
        functions: 80,
        branches: 80,
        statements: 80,
      },
    },
  },
});
