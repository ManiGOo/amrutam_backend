# Security Checklist

- [x] argon2id passwords (`time_cost=3, memory=64MB, parallelism=2`)
- [x] JWT RS256, access 15 min, refresh 7 d rotated with reuse detection, `kid`
- [x] TOTP MFA (RFC 6238) + hashed backup path; `mfa_required` gate on login
- [x] RBAC on all routes + ownership checks; admin-only analytics
- [x] PHI AES-256-GCM envelope (DEK/row, KEK env→KMS); ciphertext-only at rest
- [x] Audit append-only chain hash + advisory-locked writers; middleware covers mutations
- [x] Edge (Nginx limit_req) + app (Redis token bucket) rate limits
- [x] Security headers: HSTS, nosniff, DENY frame; CORS allowlist
- [x] Pydantic strict validation, bound SQL params, Problem+JSON errors (no leaks)
- [x] Idempotency-Key enforced on writes (replay-safe retries)
- [x] Secrets via env; one shared RS256 pair via `jwt-secrets` volume; never committed
- [x] CI: ruff + black + mypy --strict; pytest 20 green; bandit/pip-audit/trivy recommended pre-prod
- [x] SBOM/cosign signing recommended at image build (prod)
- [ ] Prod TODO: managed secrets/KMS, WAF ruleset (NAXSI/ModSecurity), TLS certs,
      REVOKE UPDATE/DELETE grants on audit_logs, PgBouncer, multi-AZ
