# certpost

Let's Encrypt certificate manager with DNS-01 challenges, web admin panel, and TLS termination proxy. Supports Cloudflare and Technitium DNS Server.

## Why?

Managing SSL certificates across multiple services is tedious — requesting certs, setting DNS records, renewing before expiry, distributing updated certs to each server. certpost automates the entire lifecycle:

1. **certpost-server** issues Let's Encrypt certificates using DNS-01 challenges, creates A/CNAME records, renews automatically, and provides an API for retrieving certs.
2. **certpost** (the client) either fetches cert files for use with nginx/haproxy/etc., or runs a TLS termination proxy that handles everything — cert fetching, TLS termination with SNI routing, and automatic refresh.

## Features

- **Automatic issuance** — ACME v2 with DNS-01 challenges, no port 80 required
- **DNS management** — creates and manages A/CNAME records alongside certificates
- **Multiple DNS providers** — Cloudflare and Technitium DNS Server, with split provider support (e.g. Cloudflare for ACME, Technitium for records)
- **Web admin panel** — manage domains, view status/logs, download certs (protected by admin key)
- **Background renewal** — checks daily, proactively renews the 2 oldest certs per day to keep them fresh
- **Per-domain tokens** — each domain gets its own API token (auto-generated, rotatable)
- **TLS termination proxy** — built-in proxy with SNI routing and automatic cert refresh
- **Certificate fetch** — save `.crt` and `.key` files, with optional scheduled refresh
- **Interactive setup** — wizards for both server and client configuration
- **Single static binary** — Go stdlib only, native crypto, no runtime dependencies
- **Modular DNS** — interface-based design makes it easy to add new providers

## Requirements

- Go 1.22+ (for building from source), or use pre-built binaries
- A supported DNS provider: Cloudflare (API token + zone ID) or Technitium DNS Server (server URL + API token)

## Quick Start

### Install

```bash
pip install certpost
```

Or build from source:

```bash
make build
```

### Set up the server

```bash
certpost-server setup -d /var/lib/certpost
certpost-server run -d /var/lib/certpost
```

The setup wizard prompts for your DNS provider settings and base domain. Open `http://localhost:8443` and log in with the admin key (printed on startup).

### Add a domain

In the admin panel, enter a subdomain and a target (IP address or CNAME hostname). certpost will:

1. Create an A or CNAME record via the configured DNS provider
2. Issue a Let's Encrypt certificate via DNS-01
3. Generate a per-domain API token

### Use the certificates

**Option A — Fetch files** for nginx, haproxy, etc.:

```bash
certpost fetch -s http://certpost:8443 -t <token> -d app.example.com -o /etc/ssl/certs
```

**Option B — TLS proxy** (all-in-one, auto-refreshes):

```bash
certpost init         # Generate proxy config interactively
certpost proxy -c certpost.json
```

See the [Usage](usage.md) page for full details.

## How It Works

certpost-server runs an HTTP server with a web admin panel and certificate retrieval API. When you add a subdomain, a background goroutine creates an A or CNAME record via the configured DNS provider, then handles the ACME v2 flow: generates keys and a CSR using native Go crypto, sets a `_acme-challenge` TXT record via the ACME DNS provider, validates with Let's Encrypt, and stores the certificate. A renewal goroutine checks daily, proactively renewing the oldest certificates (2 per day) to keep them fresh, with a safety net that forces renewal for any cert within 30 days of expiry.

The client (`certpost proxy`) fetches certificates from the server using per-domain bearer tokens, loads them into memory via `tls.X509KeyPair`, and terminates TLS using SNI to pick the right certificate for each incoming connection. Plaintext traffic is forwarded to the configured backend. Certificates are refreshed automatically on a configurable interval (default 24 hours).
