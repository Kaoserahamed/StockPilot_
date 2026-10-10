/**
 * Tests for the auth context (`lib/auth.tsx`): session bootstrap, login,
 * registration, logout, on-demand refresh and the failure paths that must still
 * clear the local session.
 *
 * `next/navigation` and the `services/auth` module are mocked, so nothing here
 * touches a router or the network while the real context logic (storage writes,
 * state transitions, redirects) is exercised.
 */

import React from 'react';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { AuthProvider, useAuth } from '../lib/auth';
import { getToken, setToken } from '../lib/session';
import * as authService from '../services/auth';
import type { AuthUser } from '../types';
import { TEST_EMAIL, MOCK_AUTH_PASSWORD } from './helpers';

const { push } = vi.hoisted(() => ({ push: vi.fn() }));

vi.mock('next/navigation', () => ({ useRouter: () => ({ push }) }));
vi.mock('../services/auth', () => ({
  me: vi.fn(),
  login: vi.fn(),
  register: vi.fn(),
  logout: vi.fn(),
}));

const owner: AuthUser = {
  id: 1,
  name: 'Maya',
  email: 'maya@shop.test',
  phone: null,
  is_active: true,
};

function Probe() {
  const { user, loading, login, register, logout, refresh } = useAuth();
  return (
    <div>
      <span data-testid="user">{user?.name ?? 'anonymous'}</span>
      <span data-testid="loading">{String(loading)}</span>
      <button onClick={() => void login(TEST_EMAIL, MOCK_AUTH_PASSWORD)}>login</button>
      <button
        onClick={() =>
          void register({
            owner_name: 'Maya',
            business_name: 'Shop',
            password: MOCK_AUTH_PASSWORD,
            email: TEST_EMAIL,
          })
        }
      >
        register
      </button>
      <button onClick={() => void logout()}>logout</button>
      <button onClick={() => void refresh()}>refresh</button>
    </div>
  );
}

function renderAuth() {
  return render(
    <AuthProvider>
      <Probe />
    </AuthProvider>
  );
}

function click(label: string) {
  return act(async () => {
    fireEvent.click(screen.getByRole('button', { name: label }));
  });
}

describe('AuthProvider', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    push.mockReset();
  });

  it('refuses to be used outside a provider', () => {
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => {});
    const errors: Error[] = [];
    // The guard throws during render. Rendering it bare lets React escalate the
    // throw to the global error handler (Vitest treats that as an unhandled
    // error), so catch it in a boundary and assert on the captured message.
    class Catch extends React.Component<{ children: React.ReactNode }> {
      state = { hasError: false };
      static getDerivedStateFromError() {
        return { hasError: true };
      }
      componentDidCatch(error: Error) {
        errors.push(error);
      }
      render() {
        return this.state.hasError ? null : this.props.children;
      }
    }
    function Bare() {
      useAuth();
      return null;
    }
    render(
      <Catch>
        <Bare />
      </Catch>
    );
    expect(errors.map((e) => e.message)).toContain('useAuth must be used inside <AuthProvider>');
    consoleError.mockRestore();
  });

  it('settles to anonymous without a stored token', async () => {
    renderAuth();

    await waitFor(() => expect(screen.getByTestId('loading').textContent).toBe('false'));
    expect(screen.getByTestId('user').textContent).toBe('anonymous');
    expect(authService.me).not.toHaveBeenCalled();
  });

  it('restores the session from a stored token', async () => {
    setToken('stored-token');
    vi.mocked(authService.me).mockResolvedValue(owner);
    renderAuth();

    expect(await screen.findByText('Maya')).toBeDefined();
    expect(screen.getByTestId('loading').textContent).toBe('false');
  });

  it('clears the session when the stored token is rejected', async () => {
    setToken('stale-token');
    vi.mocked(authService.me).mockRejectedValue(new Error('401'));
    renderAuth();

    await waitFor(() => expect(screen.getByTestId('loading').textContent).toBe('false'));
    expect(screen.getByTestId('user').textContent).toBe('anonymous');
    expect(getToken()).toBeNull();
  });

  it('logs in, stores the access token and routes to the dashboard', async () => {
    vi.mocked(authService.login).mockResolvedValue({
      access_token: 'fresh-token',
      refresh_token: 'refresh-token',
      token_type: 'bearer',
    });
    vi.mocked(authService.me).mockResolvedValue(owner);
    renderAuth();
    await waitFor(() => expect(screen.getByTestId('loading').textContent).toBe('false'));

    await click('login');

    expect(authService.login).toHaveBeenCalledWith(TEST_EMAIL, MOCK_AUTH_PASSWORD);
    expect(getToken()).toBe('fresh-token');
    expect(screen.getByTestId('user').textContent).toBe('Maya');
    expect(push).toHaveBeenCalledWith('/dashboard');
  });

  it('registers and then signs the new owner in with their email', async () => {
    vi.mocked(authService.register).mockResolvedValue(owner);
    vi.mocked(authService.login).mockResolvedValue({
      access_token: 'fresh-token',
      refresh_token: 'refresh-token',
      token_type: 'bearer',
    });
    vi.mocked(authService.me).mockResolvedValue(owner);
    renderAuth();
    await waitFor(() => expect(screen.getByTestId('loading').textContent).toBe('false'));

    await click('register');

    expect(authService.register).toHaveBeenCalledWith(
      expect.objectContaining({ owner_name: 'Maya', business_name: 'Shop' })
    );
    expect(authService.login).toHaveBeenCalledWith(TEST_EMAIL, MOCK_AUTH_PASSWORD);
    expect(push).toHaveBeenCalledWith('/dashboard');
  });

  it('logs out, clears the session and routes to the login page', async () => {
    setToken('live-token');
    vi.mocked(authService.me).mockResolvedValue(owner);
    vi.mocked(authService.logout).mockResolvedValue(undefined);
    renderAuth();
    await screen.findByText('Maya');

    await click('logout');

    expect(authService.logout).toHaveBeenCalledTimes(1);
    expect(getToken()).toBeNull();
    expect(screen.getByTestId('user').textContent).toBe('anonymous');
    expect(push).toHaveBeenCalledWith('/login');
  });

  it('still clears the session when the logout request fails', async () => {
    setToken('live-token');
    vi.mocked(authService.me).mockResolvedValue(owner);
    vi.mocked(authService.logout).mockRejectedValue(new Error('offline'));
    renderAuth();
    await screen.findByText('Maya');

    await click('logout');

    expect(getToken()).toBeNull();
    expect(screen.getByTestId('user').textContent).toBe('anonymous');
  });

  it('re-reads the identity when refresh is requested', async () => {
    setToken('live-token');
    vi.mocked(authService.me).mockResolvedValue(owner);
    renderAuth();
    await screen.findByText('Maya');

    vi.mocked(authService.me).mockClear();
    await click('refresh');

    expect(authService.me).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId('user').textContent).toBe('Maya');
  });
});
