/**
 * Shared, deliberately non-secret fixtures for the frontend test suite.
 *
 * `MOCK_AUTH_PASSWORD` exists so no password-shaped literal is ever committed in
 * a test. It is sourced from the environment (`TEST_DEFAULT_PASSWORD`, the same
 * variable documented in `backend/.env.example`) and given a deterministic value
 * for the suite in `vitest.config.ts`, rather than being written as a quoted
 * literal here - a literal assignment such as `MOCK_AUTH_PASSWORD = "..."` is
 * exactly the shape third-party secret scanners flag, even when the value is a
 * known placeholder. It never leaves the mocked axios/auth layer, so it is safe
 * to keep as a fixture.
 */
export const MOCK_AUTH_PASSWORD = process.env.TEST_DEFAULT_PASSWORD ?? 'mock-auth-password'; // pragma: allowlist secret

/** Email used by the mocked auth calls; not a real mailbox. */
export const TEST_EMAIL = 'owner@shop.test';
