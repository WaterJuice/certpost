# certpost

Let's Encrypt certificate manager with DNS-01 via Cloudflare, web admin panel, and TLS termination proxy.

## Features

- **Automatic certificate issuance** — Let's Encrypt via ACME v2, DNS-01 challenges through Cloudflare
- **Web admin panel** — manage domains, view status, download certs, view logs (protected by admin key login)
- **DNS management** — automatically creates and manages Cloudflare A records for your subdomains
- **Background renewal** — checks daily, renews certificates within 30 days of expiry
- **Per-domain API tokens** — each domain gets its own bearer token for certificate retrieval
- **TLS termination proxy** — built-in proxy with SNI routing and automatic cert refresh
- **Certificate fetching** — download `.crt` and `.key` files via CLI or admin panel
- **Interactive setup** — `certpost-server setup` and `certpost init` wizards for easy configuration
- **Zero dependencies** — stdlib only, shells out to system `openssl` for crypto
- **Modular DNS** — Cloudflare implemented, protocol-based design for adding other providers

## Requirements

- Python 3.12+
- System `openssl` binary (available on macOS and Linux)
- Cloudflare account with a DNS zone and API token

## Installation

```bash
pip install certpost
```

Or install from source:

```bash
uv pip install .
```

## Server

### Initial setup

```bash
certpost-server setup -d /path/to/data
```

This walks you through creating a `config.json` with your Cloudflare API token, zone ID, base domain, and port. An admin key is generated automatically.

### Starting the server

```bash
certpost-server run -d /path/to/data
```

The admin panel is available at `http://localhost:8443`. Log in with the admin key (printed on startup). From the panel you can:

- Add subdomains — enter an IP address or CNAME target, creates the DNS record in Cloudflare, and issues a Let's Encrypt certificate
- View certificate status and expiry dates
- Copy or rotate per-domain API tokens
- Download certificate files
- View server logs

### Configuration

The `config.json` in your data directory:

```json
{
  "cloudflare_api_token": "your-cloudflare-api-token",
  "cloudflare_zone_id": "your-zone-id",
  "base_domain": "example.com",
  "admin_key": "auto-generated-admin-key",
  "bind": "0.0.0.0",
  "port": 8443
}
```

### API

Public endpoints (no auth):

| Endpoint           | Description                              |
|--------------------|------------------------------------------|
| `GET /api/version` | Product name, API version, server version|
| `GET /api/spec`    | OpenAPI 3.0 specification               |
| `GET /api/help`    | Human-readable API documentation         |

Certificate retrieval (per-domain bearer token):

| Endpoint                | Description                         |
|-------------------------|-------------------------------------|
| `GET /api/cert/<domain>`| Certificate, chain, and private key |
| `GET /api/token-info`   | Resolve token to domain             |

Example:
```bash
curl -H "Authorization: Bearer <token>" http://certpost:8443/api/cert/app.example.com
```

## Client

### Fetch certificates

One-shot download:

```bash
certpost fetch -s http://certpost:8443 -t <token> -d app.example.com -o /etc/ssl/certs
```

With automatic refresh every 24 hours:

```bash
certpost fetch -s http://certpost:8443 -t <token> -d app.example.com --refresh 24
```

Or use a config file:

```bash
certpost fetch -c fetch.json
```

Output files: `app.example.com.crt` (full chain) and `app.example.com.key` (private key, mode 0600).

### TLS termination proxy

Run a proxy that terminates TLS, routes by SNI, and auto-refreshes certs:

```bash
certpost proxy -c proxy.json
```

Proxy config:

```json
{
  "server": "http://certpost:8443",
  "listen": "0.0.0.0:443",
  "refresh_hours": 24,
  "routes": {
    "app.example.com": {
      "token": "per-domain-api-token",
      "backend": "127.0.0.1:8080"
    },
    "api.example.com": {
      "token": "another-api-token",
      "backend": "127.0.0.1:9090"
    }
  }
}
```

### Generate a config interactively

```bash
certpost init
```

Walks you through creating either a fetch or proxy config. Auto-resolves domains from tokens and validates against the server.

## Security

- Admin panel is protected by an admin key with cookie-based auth
- Certificate API uses per-domain bearer tokens (not shared)
- Private keys are stored in JSON files — protect the data directory with filesystem permissions
- TLS proxy loads certs into memory and immediately deletes temp files

## Licence

Released under the [Unlicense](https://unlicense.org/) — public domain.
