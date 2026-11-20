# Operations runbook

All commands: `python3 tools/ctl.py <cmd>` (or `make <target>`). Output is JSON; exit 0 ok, 1 refused, 2 failed check.

| Task | Command |
|---|---|
| First run | `make setup` (installs deps, writes `.env` with random secrets, mode 600, runs `doctor`) |
| Start / stop / health | `ctl up [--port 8000]` · `ctl down` · `ctl status` (SaaS + one collector per tenant; logs `data/*.log`) |
| Add a customer | `ctl onboard gamma --region us --tz America/New_York` → restart SaaS → start the printed collector command |
| Remove a customer | `ctl offboard gamma` → restart SaaS; key + logins die at once; data stays on disk |
| Preflight | `ctl doctor` (deps, secrets strength, .env mode, tenant config, DB integrity, CA expiry, service health) |
| Backup | `ctl backup [--out dir]` – online-safe SQLite snapshot of every DB + `saas.kek` + tenants.yaml, sha256 manifest, mode 600 |
| Restore | stop services → `ctl restore <archive> --force` → `ctl doctor` → `ctl up` → `GET /api/audit/verify` |
| Metrics | `GET /metrics` with `Authorization: Bearer $METRICS_TOKEN` (Prometheus text; admin session sees own tenant only) |
| Rotate a tenant key | UI/API `POST /api/keys/rotate` (grace window keeps the old key valid for `key_grace_s`) |
| Retention | automatic: events 24 h (`SAAS_RETENTION_S`), derived history 7×; audit chain is never purged |

## Notes
- `.env` is loaded by `saas.main` and `collector.main`; real environment variables always win. Tests never read it.
- A backup holds key material (`saas.kek`): store it encrypted and off-box. `restore` verifies checksums + `integrity_check`, refuses path traversal, never overwrites `tenants.yaml`.
- Offboarding does not delete tenant rows (audit/legal hold). Purge by policy, not by this tool.
- New regions get their own database file on SaaS start; residency is enforced per file.
- Docker files are untested in the authoring sandbox (no daemon); CI runs the same drill natively.

## Console and share links (P12)
- `/console` is the customer UI (also `/`): overview + dependency map, incidents with one-click approve/reject/rollback, fleet sparklines, Ask, operations (autonomy, maintenance, webhooks), settings (people, keys, share links, audit), setup wizard. ⌘K / `/` opens the command palette; `g` then `o i f a p s` jumps between pages.
- **Share links** (Settings → Share links, or "Share read-only link" on an incident): public, no login, expiring (default 7 d, max 90 d), revocable, rate-limited, `noindex`. A status link shows component health + open incidents; an incident link shows the story and actions taken. No metrics, users, IPs, node ids or approver identities are exposed. Only a SHA-256 of the token is stored; create/revoke are audited.
- Check it in a real browser against a running stack: `make console-check USER_NAME=alpha-admin USER_PASS=...` (`tools/consolecheck.py`, add `--shots dir` for screenshots).
