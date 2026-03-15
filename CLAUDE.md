# CLAUDE.md

This file provides guidance for AI agents working on this project.

## Project Overview

certpost is a Let's Encrypt certificate manager service. It provides a web admin panel for managing subdomains and API tokens, automatically issues and renews certificates using DNS-01 challenges via the Cloudflare API, and exposes an API for other services to retrieve certificates. The client tool (`certpost`) fetches certificates from the server and saves them locally; the server runs as `certpost-server`.

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
├── cli.py            # Server CLI (certpost-server)
├── client_cli.py     # Client CLI (certpost)
├── server.py         # HTTP server (admin panel + cert API)
├── acme.py           # ACME v2 client (Let's Encrypt) using urllib + openssl
├── cloudflare.py      # Cloudflare DNS API client (for DNS-01 challenges)
├── storage.py        # JSON file storage (~/.certpost/)
├── crypto.py         # OpenSSL subprocess wrappers (key gen, CSR, JWS)
├── renewal.py        # Background certificate renewal thread
└── web/
    └── index.html    # Admin panel (embedded CSS/JS)
```

## Architecture

### Server (`certpost-server`)
- Uses stdlib `http.server` for HTTP serving (threaded)
- Admin panel at `/` for managing subdomains and API tokens
- Cert retrieval API at `/api/cert/<subdomain>` authenticated by bearer token
- Background renewal thread checks daily, renews certs within 30 days of expiry
- Storage in `~/.certpost/` as JSON files
- Thread safety via `threading.Lock` on file writes and Cloudflare API calls

### ACME / Let's Encrypt
- Implements ACME v2 protocol using `urllib.request`
- DNS-01 challenge: sets `_acme-challenge.<fqdn>` TXT record via Cloudflare API
- Crypto operations (key gen, CSR, JWS signing) via system `openssl` subprocess
- Cloudflare `setHosts` replaces all records — always fetch existing before writing

### Client (`certpost`)
- Simple tool to fetch certificates from a certpost server
- Configured with server URL and bearer token
- Saves cert, chain, and key PEM files locally
- Can run once or poll on an interval

### Auth
- Bearer tokens for API access
- Tokens stored as SHA-256 hashes (via `hashlib`)
- Admin panel manages token creation/revocation

## Testing Changes

After making changes:
1. Run `make check` to verify linting and types pass
2. Run `make build` to verify the full build works
3. Test server with `uv run certpost-server`
4. Test client with `uv run certpost`

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
