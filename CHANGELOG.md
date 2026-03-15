# certpost 1.0.0 Beta 1 - 15 Mar 2026

- Initial release
- Let's Encrypt certificate issuance via ACME v2 with DNS-01 challenges
- Namecheap DNS API integration for automated TXT record management
- Web admin panel for managing subdomains, API tokens, and configuration
- Background certificate renewal (30-day window, daily checks)
- Bearer token authenticated API for certificate retrieval
- Client tool (`certpost`) for fetching and saving certificates locally
- Zero pip dependencies — stdlib only plus system openssl
