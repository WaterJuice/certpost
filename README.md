# certpost

Let's Encrypt certificate manager with DNS-01 via Namecheap and API access.

## Features

- Web admin panel for managing subdomains and API tokens
- Automatic certificate issuance via Let's Encrypt (ACME v2, DNS-01 challenge)
- DNS record management via the Namecheap API
- Background certificate renewal (30-day window, daily checks)
- API for retrieving certificates, authenticated by bearer token
- Companion client tool for fetching and saving certificates locally

## Requirements

- Python 3.12+
- System `openssl` binary (available on macOS and Linux)
- No pip dependencies — stdlib only

## Installation

```bash
pip install certpost
```

Or install from source:

```bash
uv pip install .
```

## Server Usage

```bash
# Start the server
certpost-server --port 8443

# With custom data directory
certpost-server --data-dir /etc/certpost
```

The admin panel is available at `http://localhost:8443`. Configure your Namecheap API credentials and ACME email via the Configuration tab.

### Configuration

On first run, certpost-server creates `~/.certpost/` with a default `config.json`:

```json
{
  "namecheap_api_user": "",
  "namecheap_api_key": "",
  "namecheap_username": "",
  "namecheap_client_ip": "",
  "base_domain": "",
  "acme_email": "",
  "acme_directory": "https://acme-v02.api.letsencrypt.org/directory",
  "port": 8443
}
```

You can edit this file directly or use the admin panel.

## Client Usage

```bash
# Fetch a certificate once
certpost --server http://certpost.example.com:8443 \
         --token YOUR_TOKEN \
         --domain app.example.com \
         --output-dir /etc/ssl/certs

# Poll every 6 hours
certpost --server http://certpost.example.com:8443 \
         --token YOUR_TOKEN \
         --domain app.example.com \
         --poll 21600
```

The client saves four files: `domain.crt`, `domain.chain.crt`, `domain.fullchain.crt`, and `domain.key`.

## Security Note

Private keys are stored in JSON files under `~/.certpost/certs/`. These should be protected at the filesystem level with appropriate permissions.

## Licence

Released under the [Unlicense](https://unlicense.org/) — public domain.
