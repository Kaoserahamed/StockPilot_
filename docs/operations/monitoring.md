# Monitoring & Observability

What StockPilot exposes, how to read it, and what is worth alerting on.
Operational procedures live in [`runbook.md`](runbook.md); this document covers
the signals themselves.

---

## 1. Health endpoints

| Endpoint | Kind | Returns | Use |
|----------|------|---------|-----|
| `GET /health` | liveness | name, version, environment | compose/orchestrator `HEALTHCHECK`, uptime probe |
| `GET /health/live` | liveness alias | same | load balancer liveness |
| `GET /health/ready` | readiness | `SELECT 1` result; `503` when the DB is unreachable | remove/re-add an instance from rotation |
| `GET /health/detailed` | diagnostics | dependency status **+** error-tracking summary | incident triage (`curl` it first) |

Examples:

```bash
curl -fsS http://localhost:8000/health          # 200 {"status":"ok", ...}
curl -fsS -o /dev/null -w '%{http_code}\n' http://localhost:8000/health/ready
curl -fsS http://localhost:8000/health/detailed | jq '{database, error_tracking}'
```

`/health/detailed` is served **without authentication** and excludes PII (no
tokens, no request bodies) — it exposes exception type, route, request id and
fingerprint only. Restrict it at the network layer in any environment untrusted
parties can reach (see [`../security/threat-model.md`](../security/threat-model.md)).

## 2. Error tracking

`core/error_tracking.py` is a dependency-free tracker with three jobs:

1. **Correlate** — every captured exception carries the request id, route, method
   and the tenant/actor bound by `get_current_context` (via `ContextVar`).
2. **Aggregate** — failures are grouped by a stable fingerprint,
   `sha256("<ExceptionType>:<message>:<route>")[:16]`, with a counter per
   fingerprint and the 50 most recent reports in a bounded ring buffer. The
   `raise` line number is deliberately excluded so a refactor does not split a
   recurring issue into a new group.
3. **Forward** — if `SENTRY_DSN` is set and `sentry-sdk` is installed, reports
   fan out to Sentry; otherwise they are emitted as structured log lines.

**Concrete stack.** The error-tracking backend is **`sentry-sdk` (pinned at
`sentry-sdk==2.22.0` in `backend/requirements.txt`)**, wired through the
`SENTRY_DSN` environment variable (see `backend/.env.example`). `core/error_tracking.py`
stays dependency-free — it owns correlation and fingerprinting itself and treats
Sentry as an optional *sink*, so the tracker works with or without a DSN and the
app still boots when Sentry is not configured. `app/core/error_tracking.py` is
the module; `SENTRY_DSN` is the single knob that turns the external reporter on.
The behaviour is covered by `backend/tests/test_error_tracking.py`.

`/health/detailed` returns this summary:

| Field | Meaning |
|-------|---------|
| `enabled` / `environment` / `release` | tracker state and the deployed version |
| `sentry_installed` / `sinks` | whether a crash reporter is wired |
| `total_captured` | errors since process start (in-memory; resets on deploy) |
| `unique_fingerprints` | distinct failure groups — the number to watch |
| `last_error_at` | timestamp of the newest report |
| `recent` | up to 10 newest reports (type, message, route, request id, tenant) |

`ERROR_TRACKING_ENABLED=false` still counts in-process but stops emitting; the
tracker is always enabled when `ENVIRONMENT=test`.

## 3. Logs

`core/logging_config.setup_logging(level, json_format)` configures the root
logger on startup:

| Setting | Behaviour |
|---------|-----------|
| `JSON_LOGS=true` | one JSON object per line — the production default in `docker-compose.prod.yml`, for log collectors |
| `JSON_LOGS=false` | human-readable text (local dev) |
| `LOG_LEVEL` | `DEBUG` / `INFO` / `WARNING` / `ERROR` / `CRITICAL` |
| `RELEASE_VERSION` | stamped on every request log line and error report |

**Concrete stack.** Logging is built on the standard library `logging` module
with **`python-json-logger` (pinned at `python-json-logger==4.2.0` in
`backend/requirements.txt`)** as the JSON formatter. When `JSON_LOGS=true`,
`core/logging_config` installs `pythonjsonlogger.jsonlogger.JsonFormatter` so
each record is emitted as a single JSON object; when `false`, it falls back to a
plain-text formatter. Every line carries the `app` correlation field added by
`_ExtraFilter`, so a JSON sink can group by service. `backend/tests/test_logging_config.py`
asserts that `get_logger(__name__)` emits JSON when `JSON_LOGS=true` — the
executable proof of the documented behaviour.

Every request logs one line with `method`, `path`, `status`, `ms`, `request_id`
and `release`, so a JSON log sink can build rate/latency panels without an agent.
The response headers `X-Request-Id` and `X-Response-Time-Ms` let a browser
network trace be correlated with the server line — ask a user to send the
request id when they report a problem.

Useful queries against JSON logs:

```bash
# 5xx, with the route that produced them
jq -r 'select(.status >= 500) | "\(.status) \(.method) \(.path) \(.request_id)"' api.log

# slowest requests (any status)
jq -r 'select(.ms > 1000) | "\(.ms)ms \(.method) \(.path)"' api.log | sort -rn | head

# one incident, start to finish
grep '"request_id": "a1b2c3d4e5f60718"' api.log
```

## 4. What to alert on

These thresholds are starting points for a small deployment, not measured SLOs:

| Signal | Source | Suggested alert |
|--------|--------|-----------------|
| Readiness failing | `GET /health/ready` | `503` on 2 consecutive checks (30 s) -> page |
| 5xx rate | request logs / proxy | > 1% of requests over 5 min -> page |
| New error fingerprints | `/health/detailed` -> `unique_fingerprints` | any increase right after a deploy -> investigate immediately |
| Same fingerprint spiking | `/health/detailed` -> `recent[].fingerprint` | first occurrence is logged once; use the counter, not log volume |
| p95 latency | request logs (`ms`) | checkout > 2 s or reports > 10 s -> warn |
| `504` responses | request logs / timeout middleware | any sustained `504` -> inspect the slow path (search/checkout/reports/AI) |
| Login failures | proxy / log collector | burst against `/api/v1/auth/login` -> possible credential stuffing (§5) |
| Disk usage | host/volume | `uploads/` or backups > 80% -> act before a deploy needs space |
| DB connections | PostgreSQL `pg_stat_activity` | approaching the pool ceiling (`DB_POOL_SIZE` + `DB_MAX_OVERFLOW`, default 5 + 10) -> raise it or find the leak |
| Container health | compose `HEALTHCHECK` | unhealthy -> restart, then follow [`runbook.md`](runbook.md) |

There is **no `/metrics` endpoint** today: the application exposes logs, the
probe endpoints and the in-memory error summary. Pull-based metrics (Prometheus)
would be a new dependency and are not part of the current stack — scrape the log
sink or the reverse proxy until then.

## 5. Gaps to be aware of when alerting

| Gap | Impact |
|-----|--------|
| Error counters are in-memory and per-process | they reset on restart and are not aggregated across replicas; use the log sink for history |
| `setup_rate_limiting()` is not called (`core/rate_limit.py`) | `429`s will not appear; alert on login-failure bursts instead |
| `CSRFMiddleware` (`core/csrf.py`) is implemented but not registered | no CSRF `403`s are expected; do not build alerts on them |
| `/health/detailed` has no auth | alert noise — or information exposure if it is internet-reachable |

## 6. Database and storage checks

```bash
# connections, long-running queries
psql "$DATABASE_URL" -c "SELECT state, count(*) FROM pg_stat_activity GROUP BY state;"
psql "$DATABASE_URL" -c "SELECT pid, now()-query_start AS age, query FROM pg_stat_activity \
  WHERE state <> 'idle' ORDER BY age DESC LIMIT 5;"

# table sizes / bloat, plus reindex + analyze + vacuum
DB_PASSWORD=<secret> ./scripts/db-maintenance.sh
```

`db-maintenance.sh` prints per-table sizes after reindexing and vacuuming, which
is the cheapest way to catch an unexpectedly growing table (for example a noisy
`audit_logs`). Migration health (`alembic current` vs head) is covered in
[`../database/migrations.md`](../database/migrations.md).