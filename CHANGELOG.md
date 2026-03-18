# certpost 1.0.0 Beta 6 - 18 Mar 2026

- Initial release
- Let's Encrypt certificate issuance via ACME v2 with DNS-01 challenges
- Cloudflare DNS integration for A records and TXT record management
- Web admin panel with login, domain management, token management, and logs
- Per-domain API tokens (auto-generated, visible, rotatable)
- Background certificate renewal (30-day window, daily checks)
- TLS termination proxy with SNI routing and automatic cert refresh
- Certificate fetch CLI with optional scheduled refresh
- Interactive setup wizards for server (`certpost-server setup`) and client (`certpost init`)
- Client config validation against server during init
- DNS provider protocol for future provider support
- OpenAPI spec, version, and help API endpoints
- ISO 8601 timestamps throughout
- Zero pip dependencies — stdlib only plus system openssl
