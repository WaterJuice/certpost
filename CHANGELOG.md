# certpost 1.0.0 Beta 7 - 9 Apr 2026

- Initial release
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
- Zero pip dependencies — stdlib only plus system openssl
