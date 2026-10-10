import '@testing-library/jest-dom/vitest';
import { cleanup } from '@testing-library/react';
import { afterEach, vi } from 'vitest';

// jsdom in this repo has no `localStorage` origin configured for every test
// file, so guard the cleanup: the session tests exercise the real storage
// API while every other file gets a clean slate.
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
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
