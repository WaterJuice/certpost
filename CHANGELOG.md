# certpost 1.0.1 - 30 May 2026

Moved to new GitHub location: https://github.com/WaterJuice/certpost

# certpost 1.0.0 - 23 Apr 2026

Initial release.

- Let's Encrypt certificate issuance and renewal via ACME v2 with DNS-01 challenges
- Single static binary, zero runtime dependencies, native Go crypto (no openssl)
- Pluggable DNS provider system — Cloudflare and Technitium DNS Server supported
- Separate DNS providers for ACME challenges (TXT) and domain records (A/CNAME), or a single provider for both
- Web admin panel with login, domain management, token management, and logs
- Domains tab with collapsible rows, sort toggles (Name / Expires), substring filter, and multi-select with an Export modal (fetch config, proxy config, CSV, or ready-to-run CLI commands)
- Per-domain API tokens (auto-generated, visible in full, rotatable)
- Admin panel UI preferences persisted server-side in `prefs.json`
- HTML-escaping of all user-supplied values throughout the admin panel
- Background certificate renewal — proactively renews the 2 oldest certs daily, with a 30-day expiry safety net; errored domains retried automatically; renewal state persisted across restarts
- TLS termination proxy with SNI routing and automatic certificate refresh
- `certpost fetch` supports a single domain or a `domains` map for multiple certificates per cycle; domain optional and resolved from token via `/api/token-info`
- Interactive setup wizards for server (`certpost-server setup`) and client (`certpost init`)
- `certpost sample-config` command — prints example fetch, fetch-multi, or proxy config
- Client config validation against server during init
- OpenAPI spec, version, and help API endpoints
- Coloured CLI help (auto-disabled in pipes, respects `NO_COLOR`)
- ISO 8601 timestamps throughout
- Cross-compilation for 6 platforms (macOS/Linux/Windows × amd64/arm64)
