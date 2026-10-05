import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { describe, expect, it, vi, beforeEach } from 'vitest';

import { reportExportPath } from '../services/reports';
import Login from '../app/login/page';
import Register from '../app/register/page';
import PosPage from '../app/pos/page';
import ProductsPage from '../app/products/page';
import InventoryPage from '../app/inventory/page';
import { AuthProvider } from '../lib/auth';
import * as apiModule from '../lib/api';

// Mock Next.js router
vi.mock('next/navigation', () => ({
  useRouter: () => ({
    push: vi.fn(),
    replace: vi.fn(),
    refresh: vi.fn(),
  }),
  useSearchParams: () => ({
    get: vi.fn(),
  }),
  usePathname: () => '/',
}));

// Helper to wrap components with required providers
function renderWithProviders(ui: React.ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <AuthProvider>{ui}</AuthProvider>
    </QueryClientProvider>
  );
}

describe('authentication pages', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('login page renders form fields and submit button', () => {
    renderWithProviders(<Login />);

    expect(screen.getByRole('heading', { name: /sign in/i })).toBeDefined();
    expect(screen.getByPlaceholderText('you@shop.com')).toBeDefined();
    expect(screen.getByPlaceholderText('••••••••')).toBeDefined();
    expect(screen.getByRole('button', { name: /sign in/i })).toBeDefined();
  });

  it('login page disables submit button when fields are empty', () => {
    renderWithProviders(<Login />);

    const submitBtn = screen.getByRole('button', { name: /sign in/i });
    expect(submitBtn).toBeDisabled();
  });

  it('login page enables submit button when both fields have values', () => {
    renderWithProviders(<Login />);

    const emailInput = screen.getByPlaceholderText('you@shop.com');
    const passwordInput = screen.getByPlaceholderText('••••••••');
    const submitBtn = screen.getByRole('button', { name: /sign in/i });

    fireEvent.change(emailInput, { target: { value: 'user@test.com' } });
    fireEvent.change(passwordInput, { target: { value: 'password123' } });

    expect(submitBtn).not.toBeDisabled();
  });

  it('login page shows error message on failed authentication', async () => {
    const mockLogin = vi.fn().mockRejectedValue(new Error('Invalid credentials'));
    vi.spyOn(apiModule, 'api', 'get').mockReturnValue({
      post: mockLogin,
    } as any);

    renderWithProviders(<Login />);

    const emailInput = screen.getByPlaceholderText('you@shop.com');
    const passwordInput = screen.getByPlaceholderText('••••••••');
    const submitBtn = screen.getByRole('button', { name: /sign in/i });

    fireEvent.change(emailInput, { target: { value: 'user@test.com' } });
    fireEvent.change(passwordInput, { target: { value: 'wrong' } });
    fireEvent.click(submitBtn);

    await waitFor(() => {
      expect(screen.getByText(/invalid credentials/i)).toBeDefined();
    });
  });

  it('register page renders all required form fields', () => {
    renderWithProviders(<Register />);

    expect(screen.getByRole('heading', { name: /create.*workspace/i })).toBeDefined();
    // Check for key form elements
    expect(screen.getByPlaceholderText(/ayesha rahman/i)).toBeDefined();
    expect(screen.getByPlaceholderText(/you@shop.com/i)).toBeDefined();
  });

  it('register page has link to login for existing users', () => {
    renderWithProviders(<Register />);

    const loginLink = screen.getByText(/already.*account/i);
    expect(loginLink).toBeDefined();
  });
});

describe('pos page', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // Mock authenticated state
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation((key) => {
      if (key === 'access_token') return 'mock-token';
      if (key === 'business_id') return '1';
      return null;
    });
  });

  it('renders search input and cart heading', () => {
    renderWithProviders(<PosPage />);

    expect(screen.getByPlaceholderText(/type to search/i)).toBeDefined();
    expect(screen.getByRole('heading', { name: /cart/i })).toBeDefined();
  });

  it('shows empty cart message initially', () => {
    renderWithProviders(<PosPage />);

    expect(screen.getByText(/cart is empty/i)).toBeDefined();
  });

  it('search input triggers product search', async () => {
    const mockGet = vi.fn().mockResolvedValue({
      data: [
        { id: 1, name: 'Test Product', sku: 'TP001', quantity: 10, selling_price: 100 },
      ],
    });
    vi.spyOn(apiModule, 'api', 'get').mockReturnValue({
      get: mockGet,
    } as any);

    renderWithProviders(<PosPage />);

    const searchInput = screen.getByPlaceholderText(/type to search/i);
    fireEvent.change(searchInput, { target: { value: 'Test' } });

    await waitFor(() => {
      expect(mockGet).toHaveBeenCalledWith(expect.stringContaining('/pos/search'));
    });
  });

  it('adds product to cart when add button is clicked', async () => {
    const mockGet = vi.fn().mockResolvedValue({
      data: [
        { id: 1, name: 'Test Product', sku: 'TP001', quantity: 10, selling_price: 100 },
      ],
    });
    vi.spyOn(apiModule, 'api', 'get').mockReturnValue({
      get: mockGet,
    } as any);

    renderWithProviders(<PosPage />);

    const searchInput = screen.getByPlaceholderText(/type to search/i);
    fireEvent.change(searchInput, { target: { value: 'Test' } });

    await waitFor(() => {
      expect(screen.getByText('Test Product')).toBeDefined();
    });

    const addButton = screen.getByText('Add');
    fireEvent.click(addButton);

    await waitFor(() => {
      expect(screen.getByText(/test product × 1/i)).toBeDefined();
    });
  });
});

describe('products page', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation((key) => {
      if (key === 'access_token') return 'mock-token';
      if (key === 'business_id') return '1';
      return null;
    });
  });

  it('renders products heading with action button', () => {
    renderWithProviders(<ProductsPage />);

    expect(screen.getByRole('heading', { name: /products/i })).toBeDefined();
    expect(screen.getByRole('button', { name: /add product/i })).toBeDefined();
  });
});

describe('inventory page', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation((key) => {
      if (key === 'access_token') return 'mock-token';
      if (key === 'business_id') return '1';
      return null;
    });
  });

  it('renders inventory heading', () => {
    renderWithProviders(<InventoryPage />);

    expect(screen.getByRole('heading', { name: /inventory/i })).toBeDefined();
  });
});

describe('report export paths', () => {
  it('cover every downloadable report kind', () => {
    for (const kind of ['sales', 'inventory', 'purchases', 'expenses', 'profit'] as const) {
      expect(reportExportPath(kind, 'csv', { preset: 'all' })).toContain(`/reports/${kind}`);
      expect(reportExportPath(kind, 'pdf', { preset: 'all' })).toContain('format=pdf');
    }
  });

  it('includes query parameters in export URLs', () => {
    const path = reportExportPath('sales', 'csv', { preset: 'all' });
    expect(path).toContain('preset=all');
    // Verify the path contains expected components
    expect(path).toContain('/reports/sales');
    expect(path).toContain('format=csv');
  });
});

describe('service layer entry points', () => {
  it('exposes trading and inventory services', async () => {
    const trading = await import('../services/trading');
    const inventory = await import('../services/inventory');
    const catalogue = await import('../services/catalogue');

    expect(typeof trading.checkout).toBe('function');
    expect(typeof trading.posSearch).toBe('function');
    expect(typeof inventory.adjustStock).toBe('function');
    expect(typeof catalogue.listProducts).toBe('function');
  });
});

