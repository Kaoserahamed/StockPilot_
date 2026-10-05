# System Architecture

How StockPilot is put together, where code lives, and which rules keep the
layers honest.

| Related document | What it covers |
|------------------|----------------|
| [`data-flow.md`](data-flow.md) | Request lifecycle and the write/read paths per feature |
| [`decisions/`](decisions/) | Architecture Decision Records (why, not what) |
| [`../database/schema.md`](../database/schema.md) | Table-by-table data model |
| [`../api/authentication.md`](../api/authentication.md) | Token model, tenancy headers, RBAC |
| [`../ProjectDetails.md`](../ProjectDetails.md) | Functional requirements (FR-1 … FR-37) |

## System overview

```text
                    +-------------------+
                    |   Next.js (App    |
                    |   Router, :3000)  |
                    +--------+----------+
                             |  HTTPS/JSON (axios, Bearer + X-Business-Id)
                    +--------v----------+
                    |  FastAPI (:8000)  |
                    |  api -> services  |
                    |      -> models    |
                    +--------+----------+
                             | SQLAlchemy 2.0
                    +--------v----------+
                    |  PostgreSQL       |
                    |  (SQLite in tests)|
                    +-------------------+
```

- **Monorepo** (`decisions/0001-monorepo-layout.md`): `backend/` + `frontend/`
  versioned and released together.
- **Database:** PostgreSQL in every runtime; in-memory SQLite in tests
  (`decisions/0002-postgres-primary-sqlite-for-tests.md`).
- **AI:** deterministic SQL-backed answers first, Gemini as an optional
  rewriter (`decisions/0003-offline-first-ai.md`).
- **Auth:** short-lived access tokens + long-lived refresh tokens
  (`decisions/0004-jwt-access-refresh.md`).
- **Stock:** a single writer for `quantity_on_hand`
  (`decisions/0005-single-stock-writer.md`).

## Backend layering (`backend/app/`)

| Layer | Directory | May import | Must NOT import |
|-------|-----------|------------|-----------------|
| HTTP | `api/` (routers), `main.py` | `core`, `db`, `schemas`, `services`, `models` (read-only for tiny lookups) | contain business rules |
| Contracts | `schemas/` (Pydantic) | stdlib, Pydantic | `db`, `models`, `services` |
| Business logic | `services/` | `core`, `db`, `models` | `api`, `schemas` response types |
| Persistence | `models/` (SQLAlchemy) | `db`, stdlib | `api`, `services`, `schemas` |
| Cross-cutting | `core/` (config, security, deps, middleware, logging, errors) | stdlib + libs | `api`, `services`, `models` |
| Session | `db/` (engine, session, base) | `core` (settings) | everything else |

Rules of thumb:

1. Routers are **thin**: parse input (`schemas`), resolve the tenant
   (`core/deps.get_current_context`), call one service function, return.
2. Money rules live in `services/`. Every stock movement appends an
   `inventory_transactions` ledger row in the same commit as the quantity
   change; manual adjustments additionally go through the guarded
   `inventory_service.apply_stock_change`. See
   [`data-flow.md`](data-flow.md#2-stock-write-path-the-most-important-invariant)
   for the per-endpoint table and the known gap against
   `decisions/0005-single-stock-writer.md`.
3. Tenancy is enforced at the query level: every row read/write is filtered
   by `ctx.business_id`. Cross-tenant access returns `404`, never `403`
   (no id oracle).

## Tenancy & roles

- `User` ↔ `UserBusiness` ↔ `Business`: one login can belong to several
  businesses with a different role each.
- Request carries `Authorization: Bearer <access>` + `X-Business-Id`;
  `get_current_context` resolves `(user, business_id, role)` or `401`.
- Roles: **Owner** (everything incl. settings/plans/employees) >
  **Manager** (catalogue, trading, finance, reports) >
  **Cashier** (POS search + checkout only).
- Every mutation writes an `AuditLog` row (`services/audit.write_audit`).

## Data model (key tables)

- Identity: `users`, `user_business`, `businesses`, `password_reset_tokens`,
  `subscriptions`
- Catalogue: `categories`, `products` (image path on the row — no separate
  images table)
- Parties: `suppliers`, `customers`
- Trading: `purchases`, `purchase_items`, `sales`, `sale_items`,
  `sale_returns`, `sale_return_items`, `invoice_counters`, `expenses`
- Stock: `inventory_transactions` (append-only ledger), `price_adjustments`
- Platform: `audit_logs`, `ai_recommendations`

Every tenant-owned table carries `business_id`. The column-by-column reference,
unique constraints and indexes are in
[`../database/schema.md`](../database/schema.md).

Migrations live in `backend/alembic/`; the app also runs
`Base.metadata.create_all` plus `ensure_indexes()` on startup as a first-boot
convenience (Alembic is authoritative in production). See
[`../database/migrations.md`](../database/migrations.md).

## Frontend layering (`frontend/`)

| Layer | Directory | Responsibility |
|-------|-----------|----------------|
| Routes | `app/` (20+ pages incl. `pos/`, `ai/`) | Composition only: fetch via services, render via components |
| Components | `components/` | Presentational UI (`ui.tsx`, `Shell`, `Toast`, `Skeleton`, `ErrorBoundary`) |
| Hooks | `hooks/` | `useFormValidation`, `useKeyboardShortcuts` (POS hotkeys), `useOptimisticUpdate` |
| State | `lib/store.tsx`, `lib/auth.tsx` | Session + business context, token storage |
| Services | `services/` | One typed module per domain calling `lib/api` (axios) — the only fetch layer |
| Types | `types/` | Shared domain types; no runtime code |
| Styling | Tailwind CSS | Utility-first, no CSS-in-JS runtime |

Data flow is one-way: `app/ → services/ → lib/api → backend`, with
TanStack Query caching reads and `useOptimisticUpdate` masking write latency.

## Observability & hardening

- `core/logging_config`: structured JSON logs via `python-json-logger` in production
  (`JSON_LOGS=true`), human-readable locally; every record carries a
  correlation field (`app`) and standard fields (timestamp, level, name, message).
- `core/error_tracking`: dependency-free crash reporter with fingerprinting, aggregation,
  and optional Sentry integration (`SENTRY_DSN`); exposes recent errors via `/health/detailed`.
  Captures route, request ID, tenant, and actor context for every unhandled exception.
- `core/middleware`: `RequestContextMiddleware` (id + timing),
  `SecurityHeadersMiddleware` (HSTS/CSP/X-Frame…), `CacheHeadersMiddleware`.
- `core/exceptions`: uniform `{error: {code, message}}` envelope for every
  failure, including validation errors.
- `core/rate_limit` (slowapi) + `core/timeouts` bound abuse and hanging calls.
- Health: `/health` (liveness) and `/ready` (DB check) for orchestrators.

## Configuration

Twelve-factor via `core/config.Settings` (pydantic-settings): environment
first, `.env` fallback. Every key is documented in
`backend/.env.example`; the frontend needs only `NEXT_PUBLIC_API_URL`.
