# certpost

Let's Encrypt certificate manager with DNS-01 via Cloudflare and API access.

## Why?

Managing SSL certificates across multiple services is tedious — requesting certs, setting DNS records, renewing before expiry, distributing updated certs. certpost automates the entire lifecycle: it issues Let's Encrypt certificates using DNS-01 challenges via the Cloudflare API, renews them automatically, and provides an API for other services to fetch their certificates.

## Features

- **Web admin panel** — manage subdomains, API tokens, and configuration from your browser
- **Automatic issuance** — ACME v2 with DNS-01 challenges via the Cloudflare API
- **Background renewal** — checks daily, renews certificates within 30 days of expiry
- **Certificate API** — bearer token authenticated endpoint for retrieving cert, chain, and key
- **Client tool** — `certpost` fetches certificates from the server and saves PEM files locally
- **Polling mode** — client can poll on an interval to pick up renewed certificates
- **Zero dependencies** — stdlib only, shells out to system `openssl` for crypto
- **Simple storage** — JSON files in `~/.certpost/`, no database required

## Requirements

- Python 3.12+
- System `openssl` binary (available on macOS and Linux)
- Cloudflare account with a DNS zone and API token

## Quick Start

### Install

```bash
pip install certpost
```

Or run directly with uv:

```bash
uvx certpost-server
```

### Start the server

```bash
certpost-server --port 8443
```

Then open [http://localhost:8443](http://localhost:8443) to access the admin panel.

1. Go to the **Configuration** tab and enter your Cloudflare API token, zone ID, base domain, and ACME email
2. Go to the **Domains** tab and add a subdomain — certificate issuance starts automatically
3. Go to the **API Tokens** tab and create a token for your client services

### Fetch certificates with the client

```bash
certpost --server http://certpost.example.com:8443 \
         --token YOUR_TOKEN \
         --domain app.example.com \
         --output-dir /etc/ssl/certs
```

See the [Usage](usage.md) page for full details.

## How It Works

certpost-server runs an HTTP server with a web admin panel and a certificate retrieval API. When you add a subdomain, a background thread handles the ACME v2 flow: it generates keys and a CSR using system `openssl`, creates a DNS-01 challenge by setting a TXT record via the Cloudflare API, validates with Let's Encrypt, and stores the resulting certificate. A renewal thread checks daily and re-issues certificates approaching expiry.

The client tool (`certpost`) authenticates with a bearer token, fetches the certificate data from the API, and saves it as PEM files locally. It can run once or poll on an interval to automatically pick up renewed certificates.
