# certpost 1.0.0 Beta 9 - 9 Apr 2026

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
