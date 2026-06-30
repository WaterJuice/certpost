# certpost 1.1.0 - 30 June 2026

Adds OpenID Connect (OIDC) login as an alternative to the shared `admin_key`, so the admin
panel can delegate authentication to an existing identity provider and gate access to a
named allow-list of users.

## OIDC login

- New `oidc` config block gates the admin panel behind an OpenID Connect login
  (authorisation-code flow with PKCE), as an alternative to `admin_key`. The two are
  **mutually exclusive** — setting both is a config error.
- The provider is used purely to establish identity: no provider API is called and no
  access token is stored. Only the `preferred_username` claim from the `id_token` (falling
  back to `nickname`, as GitLab uses) is read.
- Access is an explicit allow-list: `oidc.authorised_users` lists the usernames permitted
  to log in; anyone the provider authenticates but who isn't on the list is refused with
  a 403.
- The authorise/token endpoints are learned at run time from the issuer's OIDC **discovery
  document** (`<issuer>/.well-known/openid-configuration`), fetched lazily on first login
  and cached — so the same block works against any standards-compliant provider by
  pointing `issuer` at it. Config fields: `issuer`, `client_id`, `client_secret`,
  `redirect_url` (a dedicated callback path, e.g. `/auth-callback`), `authorised_users`,
  and an optional `label` for the login button.
- The login screen shows a "Log in with &lt;label&gt;" button in OIDC mode; once signed
  in, the header shows the logged-in username, and **Logout** clears the session. Sessions
  are held in memory (so a restart logs everyone out) and carried in a one-month
  `HttpOnly` session cookie, marked `Secure` when the redirect URL is https.
- The OIDC backend is stdlib-only (`net/http`), in keeping with the project's
  zero-dependencies stance.

# certpost 1.0.1 - 30 May 2026

Moved to new GitHub location: https://github.com/WaterJuice/certpost

# certpost 1.0.0 - 23 Apr 2026

Initial release.

- Let's Encrypt certificate issuance and renewal via ACME v2 with DNS-01 challenges
- Single static binary, zero runtime dependencies, native Go crypto (no openssl)
- Pluggable DNS provider system — Cloudflare and Technitium DNS Server supported
- Separate DNS providers for ACME challenges (TXT) and domain records (A/CNAME), or a
  single provider for both
- Web admin panel with login, domain management, token management, and logs
- Domains tab with collapsible rows, sort toggles (Name / Expires), substring filter, and
  multi-select with an Export modal (fetch config, proxy config, CSV, or ready-to-run CLI
  commands)
- Per-domain API tokens (auto-generated, visible in full, rotatable)
- Admin panel UI preferences persisted server-side in `prefs.json`
- HTML-escaping of all user-supplied values throughout the admin panel
- Background certificate renewal — proactively renews the 2 oldest certs daily, with a
  30-day expiry safety net; errored domains retried automatically; renewal state persisted
  across restarts
- TLS termination proxy with SNI routing and automatic certificate refresh
- `certpost fetch` supports a single domain or a `domains` map for multiple certificates
  per cycle; domain optional and resolved from token via `/api/token-info`
- Interactive setup wizards for server (`certpost-server setup`) and client
  (`certpost init`)
- `certpost sample-config` command — prints example fetch, fetch-multi, or proxy config
- Client config validation against server during init
- OpenAPI spec, version, and help API endpoints
- Coloured CLI help (auto-disabled in pipes, respects `NO_COLOR`)
- ISO 8601 timestamps throughout
- Cross-compilation for 6 platforms (macOS/Linux/Windows × amd64/arm64)
