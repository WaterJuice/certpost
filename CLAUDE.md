# CLAUDE.md

This file provides guidance for AI agents working on this project.

## Project Overview

certpost is a Let's Encrypt certificate manager written in Go. It has two binaries:

- **certpost-server** — issues and renews SSL certificates via Let's Encrypt (ACME v2 with DNS-01 challenges), manages DNS records (A and CNAME), and provides a web admin panel and API for certificate retrieval. Supports Cloudflare and Technitium DNS Server as providers, with the ability to use different providers for ACME challenges vs domain records.
- **certpost** — client tool that fetches certificates from a certpost server. Can save them as files (`fetch`) or run a TLS termination proxy with SNI routing and automatic certificate refresh (`proxy`).

**Zero dependencies** — Go stdlib only. Native crypto (no openssl needed). Single static binary.

## Language and Spelling

Use **Australian English** throughout:
- colour (not color)
- initialise (not initialize)
- sanitise (not sanitize)
- organisation (not organization)

## Common Commands

```bash
make help              # Show all available targets
make check             # Run go vet
make build             # Build binaries into output/
make clean             # Remove build artefacts
make build-linux-amd64 # Cross-compile for Linux amd64
make build-linux-arm64 # Cross-compile for Linux arm64
```

## Project Structure

```
cmd/
├── certpost-server/
│   └── main.go           # Server CLI — run and setup commands
├── certpost/
│   └── main.go           # Client CLI — fetch, proxy, and init commands

internal/
├── version/
│   └── version.go        # Version string (set via ldflags)
├── logbuf/
│   └── logbuf.go         # In-memory ring buffer log
├── cryptoutil/
│   └── cryptoutil.go     # RSA key gen, CSR, JWS, cert parsing (native crypto)
├── storage/
│   └── storage.go        # JSON file storage for config, domains, certs
├── dns/
│   ├── provider.go       # DNS provider interface
│   ├── cloudflare.go     # Cloudflare DNS API client
│   ├── technitium.go     # Technitium DNS Server API client
│   └── factory.go        # Provider factory (creates from config)
├── acme/
│   └── client.go         # ACME v2 client (Let's Encrypt)
├── colour/
│   └── colour.go         # ANSI colour helpers (auto-disabled in pipes)
├── renewal/
│   └── renewal.go        # Background certificate renewal goroutine
├── server/
│   ├── server.go         # HTTP server (admin panel + API)
│   └── spec.go           # OpenAPI spec and help text
├── proxy/
│   └── proxy.go          # TLS termination proxy with SNI routing
├── client/
│   └── fetch.go          # Certificate fetching and saving logic
└── web/
    ├── embed.go          # go:embed directive for admin HTML
    └── index.html        # Admin panel (embedded CSS/JS, dark theme)
```

## Architecture

### Server (`certpost-server`)

Two subcommands: `run` and `setup`. Both require `--data-dir` / `-d` (no default location).

- `setup` — interactive wizard to create config.json
- `run` — starts the HTTP server, requires config.json to exist. Accepts `--demo` on beta builds (detected by `version.IsBeta()`) to swap DNS providers for a no-op stub and skip ACME init / renewal, letting the admin panel run against a real data dir without touching any external service.

Server features:
- Uses `net/http.ServeMux` with Go 1.22+ method-aware routing
- Admin panel at `/` embedded in the binary via `go:embed`
- Per-domain API tokens (auto-generated when adding a domain, visible, rotatable)
- Cert retrieval API at `/api/cert/<domain>` authenticated by per-domain bearer token
- Creates A or CNAME records via the configured DNS provider when adding domains, removes them when deleting
- Background renewal goroutine checks daily, proactively renews the 2 oldest certs per cycle to keep them fresh, with a 30-day expiry safety net. Proactive renewal timestamp persisted to avoid re-issuing on restart. Errored domains retried automatically.
- In-memory log buffer viewable in admin panel Logs tab
- Info endpoints: `/api/version`, `/api/spec` (OpenAPI 3.0), `/api/help` (plain text)
- `/api/token-info` — resolves a bearer token to its domain
- `/api/prefs` (GET/POST, admin-only) — persists admin-panel UI preferences in `prefs.json`; POST body keys are validated against an allowlist
- Admin panel Domains tab: thin collapsible rows with sort toggles (Name / Expires, ascending or descending) and a substring filter input (Esc / × to clear). Multi-select with bulk Export modal (fetch JSON, proxy JSON, CLI commands, or CSV); "Select all" scopes to the visible/filtered set. Remembers chosen sort, format, and server URL via `/api/prefs`. All user-supplied values are HTML-escaped before rendering.

### DNS Provider

- `dns/provider.go` defines a `Provider` interface with methods for TXT, A, and CNAME records
- `dns/factory.go` provides a `CreateProvider()` factory that creates providers from config maps
- `dns/cloudflare.go` implements the interface for the Cloudflare API
- `dns/technitium.go` implements the interface for the Technitium DNS Server API
- `dns/demo.go` is a no-op provider used by `certpost-server run --demo` (beta builds only); logs every call to the log buffer but makes no network requests
- The server uses two provider instances: one for ACME challenges (TXT records) and one for domain records (A/CNAME)
- A single `dns` config key can be used when both roles use the same provider; `dns_acme` and `dns_records` override individually for split configurations

### ACME / Let's Encrypt

- Implements ACME v2 protocol using `net/http`
- Let's Encrypt directory URL is hardcoded (no config needed)
- DNS-01 challenge: sets `_acme-challenge.<fqdn>` TXT record via DNS provider
- Native Go crypto: `crypto/rsa`, `crypto/x509`, `encoding/pem` — no openssl dependency
- No email registration with Let's Encrypt

### Client (`certpost`)

Four subcommands: `fetch`, `proxy`, `init`, `sample-config`. No command shows help.

- `fetch` — downloads cert as `<domain>.crt` and `<domain>.key` files. Supports `--refresh` for periodic re-fetching. Can use CLI args or a JSON config file. Config supports a single `domain`/`token` pair or a `domains` map (`{domain: token}`) for multiple certs per cycle.
- `proxy` — TLS termination proxy. Fetches certs from server, terminates TLS with SNI routing via `tls.Config.GetCertificate`, forwards plaintext to backends. Auto-refreshes certs (default 24h). Requires JSON config file.
- `init` — interactive wizard to generate a fetch or proxy config file. Resolves domains from tokens via `/api/token-info` and validates against the server. Fetch mode accepts multiple domains; writes the legacy flat form when one domain is added and a `domains` map when several are added.
- `sample-config` — prints an example config (`fetch`, `fetch-multi`, or `proxy`) to stdout, or writes it to a file with `-o`.

### Storage

- All data in a user-specified directory (`--data-dir`, no default)
- `config.json` — DNS provider settings, base domain, admin key, bind address, port
- `domains.json` — managed domains with status, target, per-domain API tokens
- `certs/<domain>/cert.json` — certificate PEM data with ISO timestamps
- `acme_account.json` — ACME account key and registration URL
- `renewal_state.json` — timestamp of last proactive renewal cycle
- `prefs.json` — admin-panel UI preferences (e.g. remembered Export format and server URL); keys restricted by an allowlist in the server
- Admin auth cookie is a SHA-256 hash of the admin key (no server-side session state)
- Atomic writes via temp file + rename, mutex-protected

### Auth

- Admin panel: login with admin key, cookie set to SHA-256 hash of key (optional "remember me" for persistence)
- Cert API: per-domain bearer tokens (generated on domain creation, rotatable)

## Testing Changes

After making changes:
1. Run `make check` to verify go vet passes
2. Run `make build` to verify the full build works
3. Test server with `./output/certpost-server run -d <dir>`
4. Test client with `./output/certpost fetch ...` or `./output/certpost proxy -c <config>`

## Versioning

- Version is injected at build time via `-ldflags "-X .../version.Version=..."`
- Create a git tag like `1.0.0` before running `make build` for a release (no `v` prefix)
- Falls back to `dev` if no tags exist

## Commits

When committing:
- Use clear, descriptive commit messages
- Include `Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>` in commits made with AI assistance
- **Never rewrite git history** unless explicitly asked to

## Licence

Released under the [Unlicense](https://unlicense.org/) — public domain.
