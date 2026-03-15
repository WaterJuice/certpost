# Usage

certpost has two commands: `certpost-server` (the infrastructure service) and `certpost` (the client tool).

## Server

### Starting the server

```bash
certpost-server
```

This starts the server on `0.0.0.0:8443` by default. Open [http://localhost:8443](http://localhost:8443) in your browser to access the admin panel.

### Server options

| Option              | Description                              |
|---------------------|------------------------------------------|
| `--port`, `-p`      | Port to listen on (default: 8443)        |
| `--host`, `-H`      | Host to bind to (default: 0.0.0.0)      |
| `--data-dir`, `-d`  | Data directory (default: ~/.certpost)    |
| `--version`         | Show version and exit                    |
| `--license`         | Show licence information and exit        |
| `--help`            | Show help and exit                       |

### Examples

```bash
# Start on a custom port
certpost-server --port 9443

# Bind to localhost only
certpost-server --host 127.0.0.1

# Custom data directory
certpost-server --data-dir /etc/certpost
```

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

You can edit this file directly or use the admin panel's Configuration tab.

### Admin panel

The admin panel has three tabs:

- **Domains** — add subdomains to manage, view certificate status and expiry dates
- **API Tokens** — create and revoke bearer tokens for API access
- **Configuration** — set Namecheap API credentials, base domain, and ACME settings

### API endpoints

| Endpoint                    | Auth   | Description                              |
|-----------------------------|--------|------------------------------------------|
| `GET /`                     | None   | Admin panel                              |
| `GET /api/domains`          | None   | List managed domains                     |
| `POST /api/domains`         | None   | Add a subdomain                          |
| `DELETE /api/domains/<fqdn>`| None   | Remove a subdomain                       |
| `GET /api/tokens`           | None   | List API tokens                          |
| `POST /api/tokens`          | None   | Create a token                           |
| `DELETE /api/tokens/<hash>` | None   | Revoke a token                           |
| `GET /api/config`           | None   | Get configuration                        |
| `POST /api/config`          | None   | Update configuration                     |
| `GET /api/cert/<fqdn>`      | Bearer | Retrieve certificate (cert, chain, key)  |

The certificate retrieval endpoint requires a bearer token in the `Authorization` header.

### Certificate response format

```json
{
  "cert_pem": "-----BEGIN CERTIFICATE-----\n...",
  "chain_pem": "-----BEGIN CERTIFICATE-----\n...",
  "key_pem": "-----BEGIN RSA PRIVATE KEY-----\n...",
  "expires_at": 1710000000.0,
  "issued_at": 1700000000.0
}
```

## Client

### Fetching certificates

```bash
certpost --server http://certpost.example.com:8443 \
         --token YOUR_TOKEN \
         --domain app.example.com
```

### Client options

| Option              | Description                                          |
|---------------------|------------------------------------------------------|
| `--server`, `-s`    | certpost server URL (required)                       |
| `--token`, `-t`     | Bearer token for authentication (required)           |
| `--domain`, `-d`    | Fully qualified domain name (required)               |
| `--output-dir`, `-o`| Directory to save files (default: current directory) |
| `--poll`            | Poll interval in seconds (0 = once, default: 0)     |
| `--version`         | Show version and exit                                |
| `--license`         | Show licence information and exit                    |
| `--help`            | Show help and exit                                   |

### Examples

```bash
# Fetch once and save to /etc/ssl/certs
certpost -s http://certpost:8443 -t mytoken -d app.example.com -o /etc/ssl/certs

# Poll every 6 hours to pick up renewed certificates
certpost -s http://certpost:8443 -t mytoken -d app.example.com --poll 21600
```

### Output files

The client saves four files per domain (dots replaced with underscores):

| File                          | Contents                    |
|-------------------------------|-----------------------------|
| `app_example_com.crt`         | Server certificate          |
| `app_example_com.chain.crt`   | Intermediate chain          |
| `app_example_com.fullchain.crt`| Certificate + chain        |
| `app_example_com.key`         | Private key (mode 0600)     |

## Running as a module

```bash
# Client
python -m certpost --server http://certpost:8443 --token mytoken --domain app.example.com
```

## Security

!!! note
    Private keys are stored in JSON files under `~/.certpost/certs/`. Protect this directory with appropriate filesystem permissions.

The admin panel has no authentication — it is intended to be accessed on a trusted network or behind a reverse proxy with its own auth layer. The certificate retrieval API is protected by bearer tokens.
