# Amrutam Telemedicine Backend

Production-grade FastAPI backend for Amrutam's telemedicine system, built for
**scalability, reliability, security, and observability**: JWT+MFA auth with RBAC,
doctor availability, idempotent concurrent-safe booking, consultation lifecycle,
sealed prescriptions, payment saga with compensations, replica search, admin
analytics, chain-hash audit trails, and full OTel observability.

- Scale: 100k daily consultations · p95 <200ms reads / <500ms writes · 99.95%
- Stack: Python 3.11 / FastAPI · PostgreSQL 16 (primary + read replica) · Redis 7 ·
  MinIO (S3) · Nginx edge · OTel → Prometheus / Loki / Tempo → Grafana
- Quality gates: `ruff` + `black` + `mypy --strict` · 23 pytest tests green · k6-measured SLOs

## 1. Quickstart

Prerequisites: Docker + Compose v2, Python 3.11+ (local dev only).

```bash
cp .env.example .env
docker compose up -d --build            # edge, api, PG primary, redis, MinIO, obs stack
docker compose exec api alembic upgrade head          # primary schema
docker compose --profile replica up -d postgres-replica
DATABASE_URL=postgresql+asyncpg://amrutam:amrutam@localhost:5434/amrutam \
  .venv/bin/alembic upgrade head                       # replica schema (demo seed)
docker compose up -d --scale api=3 --no-deps api       # start 1 api first (mints the
                                                       # shared JWT pair), then scale
curl -k https://localhost:8443/health                  # -> {"status":"ok"}
```

Entry points: API `https://localhost:8443` · Grafana `http://localhost:3000`
(admin/admin) · Prometheus `http://localhost:9090` · MinIO console `:9001` ·
MailHog `:8025`. API `:8000` is in-network only by design (all traffic via Nginx).

Local dev (no Docker):

```bash
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
docker compose up -d postgres-primary redis       # infra only
.venv/bin/alembic upgrade head
.venv/bin/python -m pytest tests/                 # 23 tests
.venv/bin/ruff check src tests && .venv/bin/black --check src tests && .venv/bin/mypy src
```

## 2. Service topology

| Service | Image / code | Ports | Role |
|---|---|---|---|
| `nginx` | `infra/nginx/amrutam.conf` | 8080→80, 8443→443 | TLS, edge rate-limit, LB with failover |
| `api` ×N | `Dockerfile` → `src/amrutam` | in-network :8000 | stateless FastAPI replicas |
| `worker` / `scheduler` | `src/amrutam/workers/` | — | outbox relay / matview-refresh cron (`--profile worker`) |
| `postgres-primary` | postgres:16 | :5432 | RW source of truth, partitioned tables |
| `postgres-replica` | postgres:16 (`--profile replica`) | :5434 | RO search + analytics |
| `redis` | redis:7 | :6379 | replay cache, buckets, streams, refresh JTIs |
| `minio` | S3-compatible | :9000/:9001 | Rx PDFs, backups |
| `otel-collector` → `prometheus`/`loki`/`tempo` → `grafana` | obs | :9090/:3100/:3200/:3000 | metrics, logs, traces, dashboards |
| `*-exporter` | postgres/redis exporters | — | DB/cache metrics into Prometheus |
| `mailhog` | dev SMTP | :8025/:1025 | notification sink (workers wedge in here) |
| k6 | `infra/k6/*.js` (adhoc container) | — | load + SLO proofs |

`docker compose config` is the machine-readable version of this table.

## 3. API overview (25 routes, `docs/api/openapi.json`)

| Area | Endpoints | Auth |
|---|---|---|
| Health | `GET /health`, `/ready`, `/metrics` | open |
| Auth | `POST /v1/auth/register\|login\|refresh`, `/mfa/enroll\|verify`, `GET /me`, `/admin/ping` | mixed |
| Doctors/slots | `GET /v1/doctors`, `POST /v1/doctors/slots`, `GET /v1/doctors/{id}/slots` | open / doctor+ |
| Bookings | `POST /v1/bookings` (`Idempotency-Key` required → 202 + `Location`) | patient |
| Consultations | `GET /v1/consultations`, `GET /{id}`, `POST /{id}/transition` (confirm/start/complete/cancel) | owner/doctor/admin |
| Prescriptions | `POST /v1/consultations/{id}/prescriptions`, `GET /v1/prescriptions/{id}`, `GET …/pdf` (5-min signed URL) | treating parties |
| Payments | `POST /v1/payments` (mock charge), `POST /v1/payments/webhook` (`X-Webhook-Secret`) | patient / gateway |
| Search | `GET /v1/search/doctors` (replica, keyset cursor) | open |
| Analytics | `GET /v1/analytics/daily\|funnel` | admin |

Errors are RFC 7807 Problem+JSON (`title/detail/code/trace_id`); auth failures 401,
ownership 403, slot races 409, throttle 429. Full schema: `docs/api/openapi.json`
(regenerated in CI).

## 4. Core flows (the 60-second version)

- **Booking:** Redis replay check → one PG tx (idempotency insert + advisory lock +
  `SELECT … FOR UPDATE SKIP LOCKED` + version-guarded hold + consultation/audit/outbox)
  → `202`. Retries are byte-identical (modulo `trace_id`); 10-way races yield 1 winner.
- **Payments (saga):** intent → mock charge → `paid` settles confirmed/booked,
  `failed` compensates cancelled/open. Webhook replays idempotently.
- **Prescriptions:** AES-256-GCM envelope (DEK/row, KEK→KMS), PDF to MinIO, presigned reads.
- **Audit:** every mutation appends a `sha256`-chained row (advisory-locked writers).

Details + diagrams: `docs/architecture.md`.

## 5. Configuration

All knobs in `.env.example` (copy to `.env`, never commit secrets):

| Var | Purpose | Default |
|---|---|---|
| `DATABASE_URL` / `REPLICA_DATABASE_URL` | PG primary (RW) / replica (RO) | compose hostnames |
| `POSTGRES_PASSWORD` | PG password (use `*_FILE` + secrets in prod) | `amrutam` (dev) |
| `REDIS_URL` | cache + idempotency + streams + buckets | `redis:6379/0` |
| `S3_ENDPOINT/ACCESS/SECRET/BUCKET` | MinIO Rx PDFs + backups | `minio:9000` |
| `JWT_*_PATH/KID/TTLs` | RS256 pair — ONE shared pair via `jwt-secrets` volume | 15 min / 7 d |
| `PRESCRIPTION_KEK_B64` | Rx envelope KEK (KMS in prod; dev default is NOT secret) | zero-key placeholder |
| `PAYMENT_WEBHOOK_SECRET` | mock-gateway webhook auth | local secret |
| `OTEL_ENABLED` / `OTEL_EXPORTER_OTLP_ENDPOINT` | tracing toggle + collector | `false` locally, `true` in compose |

## 6. Tests, CI, load

```bash
.venv/bin/python -m pytest tests/ -q                       # 23 tests (~12s, needs PG+Redis up)
.venv/bin/python -m pytest tests/test_booking.py -q        # race / replay / outbox
.venv/bin/python -m pytest --cov=src/amrutam tests/        # coverage gate (≥60%)
```

CI (`.github/workflows/ci.yml`): lint (`ruff`/`black`/`mypy --strict`) → test on
PG+Redis services (migrate + pytest + coverage) → OpenAPI export. Load:
`infra/k6/load.js` (stress), `slo*.js` (SLO runs) — measured
**reads p95 30ms / writes p95 134ms** at operating load; see `docs/load_results.md`.

Demo scripts (local-only, gitignored): `tests/demo/01_*…10_*` — numbered drag-and-run
videos-in-terminal, incl. Redis-kill, api-kill, and primary-outage injections.

## 7. Observability

- Metrics: `/metrics` (RED histogram + `bookings/payments/idempotency/outbox` counters),
  scraped per-replica; Grafana folder **Amrutam**: API RED, per-replica RED, Postgres,
  Redis, Business, SLO burn.
- Live diagrams (Eraser — architecture, booking flow sequence, observability flow,
  alert pipeline): https://app.eraser.io/workspace/yelKwDN4E3i4cYRXRGpk?origin=share
- Logs: structlog JSON on stdout → Loki; Explore by `trace_id`/`event`.
- Traces: OTel SDK → collector → Tempo (enable with `OTEL_ENABLED=true`).
- Alerts that matter: p95>200ms, 5xx>1%, payment-fail>5%, outbox lag>60s, replica lag>10s.

## 8. Security & compliance

Checklist `docs/security_checklist.md`, threat model `docs/threat_model.md` (STRIDE +
OWASP + data classification: PHI > payments > PII > operational). Highlights: argon2id,
short RS256 + rotating refresh with reuse detection, TOTP MFA, envelope-encrypted PHI,
dual rate limits, Problem+JSON without leaks, idempotent writes, append-only audit
(hot 2 yr PG, cold 7 yr parquet). Prod TODOs are marked in the checklist
(KMS, WAF, real TLS, audit `REVOKE`, PgBouncer, multi-AZ).

## 9. Operations runbook (failure drills — all scripted under `tests/demo/`)

| Kill | Expected | Recovers by |
|---|---|---|
| 1 api replica (`09`) | 9/9 OK via Nginx eviction + retry | `docker start` rejoins rotation |
| Redis (`08`) | bookings 202 via PG fallback, identical replays | restart; relay drains outbox backlog |
| PG primary (`10`) | replica reads 200; writes honestly 500 | restart; `pool_pre_ping` resumes |
| Replica lag | alert >10s; never promote without checking lag | re-seed / re-point |

Backup/DR: WAL → MinIO, RPO <5 min, RTO <30 min (promote + repoint + restart).

## 10. Repo map

```
src/amrutam/{main,core/{config,container,security,errors,idempotency,ratelimit,audit,observability},
  api/{deps,routes/health,middleware/audit},modules/{auth,doctors,bookings,consultations,
  prescriptions,payments,search,analytics},workers/{relay,scheduler}}
migrations/versions/000{1..3}_*.py   infra/{nginx,docker,otel,prometheus,tempo,grafana,k6}/
tests/{test_*.py (23, pushed), demo/ (local only)}   docs/{architecture,threat_model,
security_checklist,load_results,demo_script,api/openapi.json}
```
