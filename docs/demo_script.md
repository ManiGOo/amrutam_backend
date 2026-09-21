# 5-Minute Demo Script

— Architecture (1 diagram): edge → api×3 → PG primary/replica + Redis + MinIO → obs.
— Register doctor + patient, doctor creates slot (curl via :8443).
— Patient books with Idempotency-Key → **202 + Location**. Replay same key → identical body.
— Race: 10 parallel bookings, 1 wins + 9×409 (pytest `test_booking_race_ten_parallel_one_winner`).
— Pay (mock) → consultation `confirmed`; `force_fail` twin → `cancelled` + slot reopened (saga).
— Doctor starts consult, issues Rx → patient reads decrypted Rx + 5-min signed PDF URL.
— Search on replica, admin analytics (and patient 403).
— Observability: Grafana RED + business + SLO burn; Prometheus targets up; Tempo traces flowing.
— Failure injection: `docker stop` one api → LB keeps serving; kill redis → bookings still correct via PG.
— k6 SLO numbers (reads p95 30ms, writes p95 134ms) + honest stress note.
— Close: fail-if-missing items (idempotency, security) + repo/docs/test evidence.
