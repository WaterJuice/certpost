# certpost 1.0.0 Beta 14 - 21 Apr 2026

- Admin panel Domains tab now shows API tokens in full — removed the Show/Hide toggle and token masking

# certpost 1.0.0 Beta 13 - 16 Apr 2026

- `certpost fetch` now supports fetching multiple certificates per cycle via a `domains` map in the config file (existing single-domain configs continue to work unchanged)
- `certpost fetch --domain` is now optional — the domain is resolved from the token via `/api/token-info` when omitted; if supplied it must match
- `certpost init` prompts for multiple domains when generating a fetch config
- Added `certpost sample-config` command — prints example fetch, fetch-multi, or proxy config to stdout (or to a file with `-o`)
- Admin panel Domains tab redesigned — alphabetical sort, thin collapsible rows that expand on click, and multi-select with an Export modal that produces fetch config (single or multi-domain), proxy config, CSV (token, domain), or ready-to-run CLI commands
- Admin panel scrolls to and expands the newly-added row after "Add & Issue"
- Admin panel remembers the Export format and server URL on the server (stored in `prefs.json`); choice persists across browser sessions
- Admin panel Domains tab has a text filter — substring match on subdomain, with an inline clear button and Esc to clear; "Select all" operates on the filtered set so you can narrow then export
- Admin panel Domains tab has sort toggles for Name and Expires (click to switch field, click again to flip direction); choice is persisted in `prefs.json`
- HTML-escape user-supplied values throughout the admin panel (subdomain, target, last_error, status, filter text) — defence-in-depth against admin-controlled input rendering as HTML
- Added `certpost-server run --demo` (beta builds only) — stubs DNS calls and disables ACME/renewal so the admin UI can be explored locally without touching real services

# certpost 1.0.0 Beta 10 - 9 Apr 2026

- Coloured CLI help matching Python 3.14 argparse theme (auto-disabled in pipes, respects NO_COLOR)
- Help output written to stdout for proper pipe behaviour
- Deduplicated shared code across binaries (licence text, token generation, int parsing)
- Extracted shared `setRecord` helper in Cloudflare DNS client
- Fixed ring buffer in log module (constant memory, no GC pressure)
- Removed TOCTOU file existence checks in storage
- ACME directory re-fetched before each certificate issuance (prevents stale URL errors)
- Errored domains now retried during renewal cycle (previously silently skipped)
- Proactive renewal timestamp persisted to `renewal_state.json` — restarts no longer trigger unnecessary issuances
- Simplified `--version` output (removed Go runtime version)
- Added venv symlinks to `make build` target
- Fixed CI pipeline — Go now installed in Docker image

# certpost 1.0.0 Beta 7 - 8 Apr 2026

- Initial Go release — complete rewrite from Python to Go
- Single static binary, zero runtime dependencies, native crypto
- Let's Encrypt certificate issuance via ACME v2 with DNS-01 challenges
- Pluggable DNS provider system — Cloudflare and Technitium DNS Server supported
- Separate DNS providers for ACME challenges (TXT) and domain records (A/CNAME), or a single provider for both
- Config supports a shared `dns` key for single-provider setups and `dns_acme`/`dns_records` for split configurations
- Automatic migration of legacy flat Cloudflare configs to the new provider format
- Web admin panel with login, domain management, token management, and logs
- Per-domain API tokens (auto-generated, visible, rotatable)
- Background certificate renewal — proactively renews the 2 oldest certs daily, with a 30-day expiry safety net
- TLS termination proxy with SNI routing and automatic cert refresh
- Certificate fetch CLI with optional scheduled refresh
- Interactive setup wizards for server (`certpost-server setup`) and client (`certpost init`)
- Client config validation against server during init
- OpenAPI spec, version, and help API endpoints
- ISO 8601 timestamps throughout
- Cross-compilation for 6 platforms (macOS/Linux/Windows × amd64/arm64)
