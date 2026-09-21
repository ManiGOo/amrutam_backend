# Load Results (k6, honest numbers)

Scripts: `infra/k6/load.js` (stress), `infra/k6/slo.js`, `infra/k6/slo_focused.js`.
Ran in-network (`--network amrutam_backend_app`, `BASE_URL=http://api:8000`),
3 api replicas, seeded replica (1500 doctors), primary + Redis shared.

## SLO run — 20 read VUs + 10 write VUs (~220 rps, 2 min)

- reads: med 7ms, **p95 30ms** (SLO <200ms ✓)
- writes: med 52ms, **p95 134ms** (SLO <500ms ✓)
- checks 100%, 202/409/429 all treated as settled
- conclusion: operating point (~50 rps peak) passes with wide margin

## Stress run — 500 read VUs + 20 write VUs (~380 rps, 2 min)

- reads p95 1.8s ✗, writes p95 986ms ✗ — pool-bound (20+15 conns/replica)
- found + fixed during this run: per-replica JWT keypairs caused cross-replica
  401s → shared `jwt-secrets` volume (start 1 replica, then `--scale api=3`)
- fix path: larger pools, more replicas, PgBouncer, async audit writer

## Edge layer (verified separately)

- `curl -k https://localhost:8443/health` → 200 via Nginx TLS + LB
- 9/9 authenticated requests succeed across 3 replicas (shared keypair proof)
- `limit_req` (20r/s IP, 10r/s JWT) + `max_fails=3` eviction configured
