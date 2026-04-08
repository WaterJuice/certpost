# certpost

Let's Encrypt certificate manager with DNS-01 challenges, web admin panel, and TLS termination proxy. Written in Go — single static binary, no dependencies. Supports Cloudflare and Technitium DNS Server.

## Features

- **Automatic certificate issuance** — Let's Encrypt via ACME v2, DNS-01 challenges
- **Multiple DNS providers** — Cloudflare and Technitium DNS Server, with split provider support (e.g. Cloudflare for ACME, Technitium for records)
- **Web admin panel** — manage domains, view status, download certs, view logs (protected by admin key login)
- **DNS management** — automatically creates and manages A/CNAME records for your subdomains
- **Background renewal** — proactively renews the 2 oldest certs daily, with a 30-day expiry safety net
- **Per-domain API tokens** — each domain gets its own bearer token for certificate retrieval
- **TLS termination proxy** — built-in proxy with SNI routing and automatic cert refresh
- **Certificate fetching** — download `.crt` and `.key` files via CLI or admin panel
- **Interactive setup** — `certpost-server setup` and `certpost init` wizards for easy configuration
- **Single static binary** — no runtime dependencies, no openssl required
- **Modular DNS** — protocol-based design makes it easy to add new providers

## Requirements

- Go 1.22+ (for building)
- A supported DNS provider: Cloudflare (API token + zone ID) or Technitium DNS Server (server URL + API token)

## Building

```bash
make build
```

Produces `output/certpost-server` and `output/certpost`.

Cross-compile for Linux:

```bash
make build-linux-amd64
make build-linux-arm64
```

## Server

### Initial setup

```bash
certpost-server setup -d /path/to/data
```

This walks you through creating a `config.json` with your DNS provider settings, base domain, and port. An admin key is generated automatically.

### Starting the server

```bash
certpost-server run -d /path/to/data
```

The admin panel is available at `http://localhost:8443`. Log in with the admin key (printed on startup). From the panel you can:

- Add subdomains — enter an IP address or CNAME target, creates the DNS record via the configured provider, and issues a Let's Encrypt certificate
- View certificate status and expiry dates
- Copy or rotate per-domain API tokens
- Download certificate files
- View server logs

### Configuration

The `config.json` in your data directory. Use a single `dns` key when one provider handles everything:

```json
{
  "base_domain": "example.com",
  "admin_key": "auto-generated-admin-key",
  "bind": "0.0.0.0",
  "port": 8443,
  "dns": {
    "provider": "cloudflare",
    "api_token": "your-cloudflare-api-token",
    "zone_id": "your-zone-id"
  }
}
```

For split configurations, use `dns_acme` and `dns_records`:

```json
{
  "base_domain": "example.com",
  "admin_key": "auto-generated-admin-key",
  "bind": "0.0.0.0",
  "port": 8443,
  "dns_acme": {
    "provider": "cloudflare",
    "api_token": "your-cloudflare-api-token",
    "zone_id": "your-zone-id"
  },
  "dns_records": {
    "provider": "technitium",
    "server_url": "https://dns.example.com",
    "api_token": "your-technitium-api-token",
    "zone": "example.com"
  }
}
```

## Client

### Fetch certificates

```bash
certpost fetch -s http://certpost:8443 -t <token> -d app.example.com -o /etc/ssl/certs
```

With automatic refresh every 24 hours:

```bash
certpost fetch -s http://certpost:8443 -t <token> -d app.example.com --refresh 24
```

### TLS termination proxy

```bash
certpost proxy -c proxy.json
```

### Generate a config interactively

```bash
certpost init
```

## Security

- Admin panel is protected by an admin key with cookie-based auth
- Certificate API uses per-domain bearer tokens (not shared)
- Private keys are stored in JSON files — protect the data directory with filesystem permissions
- TLS proxy loads certs directly into memory via `tls.X509KeyPair` — no temp files

## Licence

Released under the [Unlicense](https://unlicense.org/) — public domain.
