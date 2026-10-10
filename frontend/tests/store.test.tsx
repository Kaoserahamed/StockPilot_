import React from 'react';
import { act, fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { StoreProvider, useStore } from '../lib/store';

/** Exposes every store action through a button so tests can drive it. */
function Probe() {
  const store = useStore();
  return (
    <div>
      <span data-testid="lines">{store.cart.map((item) => item.product_id).join(',')}</span>
      <span data-testid="units">{store.cart.map((item) => item.quantity).join(',')}</span>
      <span data-testid="total">{store.cartTotal}</span>
      <span data-testid="toasts">
        {store.toasts.map((toast) => `${toast.type}:${toast.message}`).join('|')}
      </span>
      <span data-testid="theme">{store.userPreferences.theme}</span>
      <span data-testid="compact">{String(store.userPreferences.compact)}</span>

      <button onClick={() => store.addToCart({ product_id: 1, name: 'Rice', unit_price: 10 })}>
        add-one
      </button>
      <button
        onClick={() =>
          store.addToCart({ product_id: 1, name: 'Rice', unit_price: 10, quantity: 3 })
        }
      >
        add-three
      </button>
      <button onClick={() => store.addToCart({ product_id: 2, name: 'Oil', unit_price: 5 })}>
        add-other
      </button>
      <button onClick={() => store.updateCartQty(1, 0)}>zero</button>
      <button onClick={() => store.updateCartQty(2, 7)}>seven</button>
      <button onClick={() => store.removeFromCart(1)}>remove</button>
      <button onClick={() => store.clearCart()}>clear</button>
      <button onClick={() => store.toast('Saved', 'success')}>toast</button>
      <button
        onClick={() => {
          const first = store.toasts[0];
          if (first) store.dismissToast(first.id);
        }}
      >
        dismiss
      </button>
      <button onClick={() => store.setPreference('theme', 'dark')}>dark</button>
      <button onClick={() => store.setPreference('compact', true)}>compact</button>
    </div>
  );
}

function renderStore() {
  return render(
    <StoreProvider>
      <Probe />
    </StoreProvider>
  );
}

function click(label: string): void {
  fireEvent.click(screen.getByText(label));
}

describe('StoreProvider', () => {
  it('starts with an empty cart, a zero total and the default preferences', () => {
    renderStore();
    expect(screen.getByTestId('lines').textContent).toBe('');
    expect(screen.getByTestId('total').textContent).toBe('0');
    expect(screen.getByTestId('theme').textContent).toBe('light');
    expect(screen.getByTestId('compact').textContent).toBe('false');
  });

  it('adds a line, merges a repeat product and accumulates the total', () => {
    renderStore();

    click('add-one');
    click('add-other');
    expect(screen.getByTestId('lines').textContent).toBe('1,2');
    expect(screen.getByTestId('units').textContent).toBe('1,1');
    expect(screen.getByTestId('total').textContent).toBe('15');

    // The same product is merged rather than duplicated.
    click('add-one');
    expect(screen.getByTestId('lines').textContent).toBe('1,2');
    expect(screen.getByTestId('units').textContent).toBe('2,1');
    expect(screen.getByTestId('total').textContent).toBe('25');

    // An explicit quantity is honoured.
    click('add-three');
    expect(screen.getByTestId('units').textContent).toBe('5,1');
    expect(screen.getByTestId('total').textContent).toBe('55');
  });

  it('updates a quantity, clamps non-positive values to a removal, and empties the cart', () => {
    renderStore();
    click('add-one');
    click('add-other');

    click('seven');
    expect(screen.getByTestId('units').textContent).toBe('1,7');
    expect(screen.getByTestId('total').textContent).toBe('45');

    // A non-positive quantity removes the line instead of storing zero.
    click('zero');
    expect(screen.getByTestId('lines').textContent).toBe('2');
    expect(screen.getByTestId('units').textContent).toBe('7');

    // Removing an absent product is a no-op, not a crash.
    click('remove');
    expect(screen.getByTestId('lines').textContent).toBe('2');

    click('add-one');
    expect(screen.getByTestId('lines').textContent).toBe('2,1');

    click('clear');
    expect(screen.getByTestId('lines').textContent).toBe('');
    expect(screen.getByTestId('total').textContent).toBe('0');
  });

  it('queues toasts with their tone, dismisses them, and clears them on a timer', () => {
    vi.useFakeTimers();
    try {
      renderStore();

      click('toast');
      expect(screen.getByTestId('toasts').textContent).toBe('success:Saved');

      click('dismiss');
      expect(screen.getByTestId('toasts').textContent).toBe('');

      click('toast');
      act(() => {
        vi.advanceTimersByTime(4000);
      });
      expect(screen.getByTestId('toasts').textContent).toBe('');
    } finally {
      vi.useRealTimers();
    }
  });

  it('stores user preferences', () => {
    renderStore();

    click('dark');
    click('compact');
    expect(screen.getByTestId('theme').textContent).toBe('dark');
    expect(screen.getByTestId('compact').textContent).toBe('true');
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
    render(
      <Catch>
        <Probe />
      </Catch>
    );
    expect(errors.map((e) => e.message)).toContain('useStore must be used within StoreProvider');
    consoleError.mockRestore();
  });
});
