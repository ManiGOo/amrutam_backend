# Threat Model (STRIDE per component + OWASP mapping)

## Attack surface

| Component | Exposed to | Trust boundary |
|---|---|---|
| Nginx :80/:8443 | Internet | TLS ends here; WAF + limit_req |
| FastAPI :8000 | Compose network only | JWT + RBAC + validation |
| Postgres :5432/:5434 | Compose + dev host | App role, no direct Internet |
| Redis :6379 | Compose + dev host | No auth locally; password + SGs in prod |
| MinIO :9000 | Compose + dev host | Presigned URLs (5-min TTL), no public bucket |
| Grafana :3000 | Dev host | admin/admin locally; SSO/OAuth in prod |

## STRIDE

- **Spoofing** → RS256 JWT (15-min access, rotating 7-day refresh with reuse
  detection), TOTP MFA, argon2id passwords. Webhook shared secret.
- **Tampering** → TLS everywhere, audit chain-hash (`sha256(prev‖…)`), advisory
  lock against chain forks, JWT `kid` rotation.
- **Repudiation** → append-only audit on every mutation (middleware + services),
  outbox event log, idempotency_keys permanent record.
- **Information disclosure** → AES-256-GCM envelope for PHI (DEK/row, KEK/env→KMS),
  soft-delete for users/Rx, CORS allowlist, no stack leaks (Problem+JSON + trace_id).
- **Denial of service** → edge + app rate limits, `SKIP LOCKED` fail-fast (no lock
  queues), pool caps, `max_fails` eviction, p95/5xx alerts.
- **Elevation of privilege** → RBAC on every route (`require_role`), doctor/patient
  ownership checks, admin-only analytics, webhook secret ≠ user auth.

## OWASP Top 10 mapping

1. Broken Access Control → RBAC + ownership tests. 2. Cryptographic Failures →
   TLS, envelope encryption, argon2id. 3. Injection → bound params only, Pydantic
   strict (`extra=forbid`). 4. Insecure Design → idempotency/saga/chain-lock by
   design. 5. Misconfig → `.env.example`, no checked-in secrets, security headers.
   6. Vuln components → pip-audit/bandit/trivy in CI. 7. Auth failures → short JWT,
   rotation, MFA, lockout via rate limit. 8. Integrity → SBOM/cosign, chain hash.
   9. Logging gaps → structlog JSON + trace ids + audit. 10. SSRF → egress allowlist,
   `trust_env=False` clients.

## Data classification

PHI (diagnosis/Rx) > payments > PII (email/phone) > operational (metrics).
PHI never in logs; PDFs encrypted at rest + presigned reads.

## Residual risks (accepted, documented)

- Single-region compose demo (prod: multi-AZ, managed PG/Redis).
- Self-signed TLS locally (prod: ACM/LetsEncrypt).
- Audit chain serializes writers (mitigation: async audit worker at scale).
- Mock payment gateway (prod: Razorpay/Stripe + signature verification).
