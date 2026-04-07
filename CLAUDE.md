# CLAUDE.md

This file provides guidance for AI agents working on this project.

## Project Overview

certpost is a Let's Encrypt certificate manager. It has two components:

- **certpost-server** — issues and renews SSL certificates via Let's Encrypt (ACME v2 with DNS-01 challenges), manages DNS records (A and CNAME), and provides a web admin panel and API for certificate retrieval. Supports Cloudflare and Technitium DNS Server as providers, with the ability to use different providers for ACME challenges vs domain records.
- **certpost** — client tool that fetches certificates from a certpost server. Can save them as files (`fetch`) or run a TLS termination proxy with SNI routing and automatic certificate refresh (`proxy`).

**Zero pip dependencies** — stdlib only plus system `openssl`. No asyncio; uses threading.

## Language and Spelling

Use **Australian English** throughout:
- colour (not color)
- initialise (not initialize)
- sanitise (not sanitize)
- organisation (not organization)

## Code Style

### Python Files

Every Python file should have:
1. A file header block with description and version history
2. Section headers separating major sections (Imports, Constants, Functions, etc.)
3. Horizontal separators (92 chars of `-`) above each function definition

Example structure:
```python
# ----------------------------------------------------------------------------------------
#   filename.py
#   -----------
#
#   Brief description of what this module does.
#
#   (c) 2026 WaterJuice — Released under the Unlicense; see LICENSE.
#
#   Version History
#   ---------------
#   Mar 2026 - Created
# ----------------------------------------------------------------------------------------

# ----------------------------------------------------------------------------------------
#   Imports
# ----------------------------------------------------------------------------------------

import sys

# ----------------------------------------------------------------------------------------
#   Functions
# ----------------------------------------------------------------------------------------


# ----------------------------------------------------------------------------------------
def my_function() -> None:
    """Docstring here."""
    pass
```

### General

- Python 3.12+ (do **not** use `from __future__ import annotations`)
- Use type hints throughout
- Prefer pathlib.Path over os.path
- Single-line imports, no blank lines between import groups (configured in pyproject.toml)
- Run `make format` to auto-fix import ordering
- **No external dependencies** — stdlib only, shell out to `openssl` for crypto
- CLI uses argbuilder.py (custom argparse wrapper)
- Tokens use lowercase alphanumeric characters only (a-z, 0-9), 40 chars
- Timestamps use ISO 8601 format, not Unix epoch floats

## Common Commands

```bash
make help       # Show all available targets
make check      # Run ruff + pyright
make format     # Auto-fix and format code
make build      # Build wheel + docs into output/
make docs       # Build HTML documentation into html/
make clean      # Remove build artefacts
make dev        # Just create dev (.venv) setup
```

## Project Structure

```
certpost/
├── __init__.py       # Package init, exports __version__
├── __main__.py       # Entry point for python -m certpost
├── version.py        # Version string handling
├── argbuilder.py     # Custom argparse wrapper
├── cli.py            # Server CLI (certpost-server) — run and setup commands
├── client_cli.py     # Client CLI (certpost) — fetch, proxy, and init commands
├── client_fetch.py   # Certificate fetching and saving logic (shared by client and proxy)
├── server.py         # HTTP server (admin panel + cert API + info endpoints)
├── proxy.py          # TLS termination proxy with SNI routing and auto-refresh
├── acme.py           # ACME v2 client (Let's Encrypt) using urllib + openssl
├── cloudflare.py     # Cloudflare DNS API client (A/CNAME records + TXT records)
├── technitium.py     # Technitium DNS Server API client (A/CNAME records + TXT records)
├── dns.py            # DNS provider protocol and factory (creates providers from config)
├── storage.py        # JSON file storage for config, domains, certs
├── crypto.py         # OpenSSL subprocess wrappers (key gen, CSR, JWS)
├── renewal.py        # Background certificate renewal thread
├── log.py            # In-memory log buffer (ring buffer, also prints to stderr)
└── web/
    └── index.html    # Admin panel (embedded CSS/JS, dark theme)
```

## Architecture

### Server (`certpost-server`)

Two subcommands: `run` and `setup`. Both require `--data-dir` (no default location).

- `setup` — interactive wizard to create config.json
- `run` — starts the HTTP server, requires config.json to exist

Server features:
- Uses stdlib `http.server` for HTTP serving (threaded)
- Admin panel at `/` protected by admin key login with cookie auth
- Per-domain API tokens (auto-generated when adding a domain, visible, rotatable)
- Cert retrieval API at `/api/cert/<domain>` authenticated by per-domain bearer token
- Creates A or CNAME records via the configured DNS provider when adding domains, removes them when deleting
- Background renewal thread checks daily, renews certs within 30 days of expiry
- In-memory log buffer viewable in admin panel Logs tab
- Info endpoints: `/api/version`, `/api/spec` (OpenAPI 3.0), `/api/help` (plain text)
- `/api/token-info` — resolves a bearer token to its domain

### DNS Provider

- `dns.py` defines a `DnsProvider` protocol with methods for TXT, A, and CNAME records
- `dns.py` also provides a `create_dns_provider()` factory that creates providers from config dicts
- `cloudflare.py` implements the protocol for the Cloudflare API
- `technitium.py` implements the protocol for the Technitium DNS Server API
- The server uses two provider instances: one for ACME challenges (TXT records) and one for domain records (A/CNAME)
- A single `dns` config key can be used when both roles use the same provider; `dns_acme` and `dns_records` override individually for split configurations

### ACME / Let's Encrypt

- Implements ACME v2 protocol using `urllib.request`
- Let's Encrypt directory URL is hardcoded (no config needed)
- DNS-01 challenge: sets `_acme-challenge.<fqdn>` TXT record via DNS provider
- Crypto operations (key gen, CSR, JWS signing) via system `openssl` subprocess
- No email registration with Let's Encrypt

### Client (`certpost`)

Three subcommands: `fetch`, `proxy`, `init`. No command shows help.

- `fetch` — downloads cert as `<domain>.crt` and `<domain>.key` files. Supports `--refresh` for periodic re-fetching. Can use CLI args or a JSON config file.
- `proxy` — TLS termination proxy. Fetches certs from server, terminates TLS with SNI routing, forwards plaintext to backends. Auto-refreshes certs (default 24h). Requires JSON config file.
- `init` — interactive wizard to generate a fetch or proxy config file. Resolves domains from tokens via `/api/token-info` and validates against the server.

### Storage

- All data in a user-specified directory (`--data-dir`, no default)
- `config.json` — DNS provider settings, base domain, admin key, bind address, port
- `domains.json` — managed domains with status, IP, per-domain API tokens
- `certs/<domain>/cert.json` — certificate PEM data with ISO timestamps
- `acme_account.json` — ACME account key and registration URL
- Admin auth cookie is a SHA-256 hash of the admin key (no server-side session state)

### Auth

- Admin panel: login with admin key, cookie set to SHA-256 hash of key (optional "remember me" for persistence)
- Cert API: per-domain bearer tokens (generated on domain creation, rotatable)

## Testing Changes

After making changes:
1. Run `make check` to verify linting and types pass
2. Run `make build` to verify the full build works
3. Test server with `uv run certpost-server run -d <dir>`
4. Test client with `uv run certpost fetch ...` or `uv run certpost proxy -c <config>`

**Important:** The server does not hot-reload. Always restart after code changes.

## Versioning

- Version is derived from git tags via uv-dynamic-versioning
- Create a tag like `1.0.0` before running `make build` for a release (no `v` prefix)
- The build generates `_version.py` at build time, which is not committed
- If no tags exist, version falls back to "dev"

## Commits

When committing:
- Use clear, descriptive commit messages
- Include `Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>` in commits made with AI assistance
- **Never rewrite git history** unless explicitly asked to

## Licence

Released under the [Unlicense](https://unlicense.org/) — public domain.
