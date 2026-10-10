import '@testing-library/jest-dom/vitest';
import { cleanup } from '@testing-library/react';
import { afterEach, vi } from 'vitest';

/**
 * Errors React caught with an error boundary.
 *
 * React's development build reports every boundary-caught render error through
 * the global `reportError` (it falls back to `console.error` when absent).
 * jsdom implements `reportError` as an *uncaught*-exception reporter, so each
 * error-boundary test prints "Uncaught [Error: kaboom]" on a run that is
 * otherwise green. That reads like a failure in CI and invites false alarms.
 *
 * Collect them here instead: the run stays quiet, and the errors are still
 * observable to any test that wants to assert on them. Only boundary-caught
 * errors take this path - genuinely uncaught exceptions and failed assertions
 * still fail the suite through Vitest's own reporting.
 */
export const recoverableErrors: unknown[] = [];

window.reportError = ((error: unknown) => {
  recoverableErrors.push(error);
}) as typeof window.reportError;

// jsdom in this repo has no `localStorage` origin configured for every test
// file, so guard the cleanup: the session tests exercise the real storage
// API while every other file gets a clean slate.
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  recoverableErrors.length = 0;
  try {
    localStorage.clear();
  } catch {
    /* storage unavailable in this test environment */
  }
  try {
    sessionStorage.clear();
  } catch {
    /* storage unavailable in this test environment */
  }
});
