# Session Summary — 8 Apr 2026

## Overview

Complete rewrite of certpost from Python to Go, plus multi-DNS provider support, bin2whl multi-binary feature, and various UI/build improvements.

## 1. Technitium DNS Provider (Python branch, before rewrite)

- **Created `certpost/technitium.py`** — full Technitium DNS Server API client implementing the `DnsProvider` protocol (TXT, A, CNAME record management)
- **Updated `certpost/dns.py`** — added `create_dns_provider()` factory function that creates either Cloudflare or Technitium clients from config dicts
- **Split DNS provider support** — the server now uses two separate DNS providers: one for ACME challenges (TXT records) and one for domain records (A/CNAME)
- **Config format** — single `dns` key for same-provider setups; `dns_acme` and `dns_records` for split configurations; automatic migration of legacy flat `cloudflare_*` keys
- **Updated setup wizard** — prompts for provider type per role, offers to reuse the same provider for both
- Verified Technitium API works (tested TXT, A record add/delete against `dns66.clearnet.dev`)

## 2. Proactive Certificate Renewal

- Changed renewal from "only renew within 30 days of expiry" to proactively renewing the **2 oldest certificates per day**
- 30-day expiry window remains as a safety net
- With 19 domains, each cert gets refreshed roughly every 10 days (14/week, well within Let's Encrypt's 50/week limit)

## 3. Admin Panel Improvements

- **Beta ribbon** — diagonal amber banner on top-left, auto-hides for stable releases (checks `/api/version` for letters in version string), set to 50% transparency
- **Version display** — server version shown in header after "certpost certificate manager"

## 4. Go Rewrite (branch: `golang`)

Complete rewrite of certpost from Python to Go. **17 Go source files, ~3,500 lines.**

### Project Structure
```
cmd/certpost-server/main.go    — Server CLI (run, setup)
cmd/certpost/main.go            — Client CLI (fetch, proxy, init)
internal/version/               — Version string (ldflags)
internal/logbuf/                — In-memory ring buffer log
internal/cryptoutil/            — Native crypto (RSA, CSR, JWS, cert parsing)
internal/storage/               — JSON file storage (config, domains, certs)
internal/dns/                   — Provider interface, Cloudflare, Technitium, factory
internal/acme/                  — ACME v2 client (Let's Encrypt)
internal/renewal/               — Background renewal goroutine
internal/server/                — HTTP server (admin panel + API)
internal/proxy/                 — TLS termination proxy with SNI routing
internal/client/                — Certificate fetch/save logic
internal/web/                   — go:embed admin panel HTML
```

### Key Improvements Over Python
- **Single static binary** — no runtime dependencies, no venv, no pip
- **Native crypto** — `crypto/rsa`, `crypto/x509` replace all openssl subprocesses
- **TLS proxy uses `tls.Config.GetCertificate`** — proper SNI cert selection, certs loaded via `tls.X509KeyPair` directly into memory (no temp files)
- **`go:embed`** — admin panel HTML compiled into binary
- **Cross-compilation** — 6 platforms (macOS/Linux/Windows × amd64/arm64)
- **Go 1.22+ `ServeMux`** — method-aware routing, no third-party router

### Full Compatibility Maintained
- Same config.json format (dns, dns_acme/dns_records, legacy migration)
- Same domains.json and cert.json format
- Same API endpoints (all 15 routes)
- Same CLI flags and subcommands
- Same auth model (SHA-256 cookie, bearer tokens, 40-char tokens)
- Same renewal behaviour (2 oldest daily + 30-day safety net)

### Bug Fixes From Review
- Fixed `http.NewRequest` error handling (was ignoring errors, risking nil pointer panics)
- Added HTTP status check on certificate download
- Fixed proxy `CloseWrite` to use interface assertion (works for both TCP and TLS connections)

## 5. bin2whl Multi-Binary Support

Updated bin2whl (separate project at `/Users/carrot/code/waterjuice/bin2whl/`) to support **multiple binaries per wheel**. Published as 1.0.0b4.

### Changes
- **config.py** — `binaries` values can now be a list of `{name, path}` objects (backwards compatible — strings still work)
- **wheel_builder.py** — `build_wheel` accepts a `binaries` parameter (list of `BinarySpec`), each gets its own entry in `.data/scripts/`
- **cli.py** — passes multi-binary entries through, updated example config
- All docs updated (CHANGELOG, README, config.md, index.md, CLAUDE.md)

## 6. Build System (certpost)

- **wheel.json** — maps 6 platforms to pairs of binaries (certpost-server + certpost)
- **pyproject.toml** — dev dependencies: bin2whl, cal-mkdocs, cal-publish-python
- **Makefile** — full target set:
  - `make build` — cross-compile 12 binaries, build 6 wheels, docs, docs zip
  - `make build-local` — build for current platform only (fast)
  - `make check` — gofmt check + go vet
  - `make format` — gofmt all Go files
  - `make docs` — build HTML docs with cal-mkdocs
  - `make dev` — build + symlink into .venv/bin
  - `make clean` — remove all build artefacts
  - `make publish` — publish to registry

## 7. Documentation Updates

All documentation updated throughout the session to reflect:
- Multi-DNS provider support
- Proactive renewal behaviour
- Go rewrite (project structure, build commands, architecture)
- Removed all Python-specific references
- CLAUDE.md, README.md, CHANGELOG.md, docs/mkdocs/* all current

## Commits Made

### certpost repo (branch: `dev`, then `golang`)
1. `011ea48` — Add Technitium DNS provider and split DNS provider support
2. `f4bfb7b` — Add beta ribbon and version display to admin panel
3. `b841eb2` — Proactive certificate renewal — renew 2 oldest certs daily
4. Go rewrite and build system changes (uncommitted on `golang` branch)

### bin2whl repo
1. `cccff62` — Add multi-binary support — multiple binaries per wheel

## Test Data

- `testdata/` directory contains full copy of production data from `calservice` (config, domains, certs, ACME account) with split Cloudflare/Technitium config
- Server tested and verified working with Go binary against this data
