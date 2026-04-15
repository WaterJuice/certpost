# Usage

certpost has two commands: `certpost-server` (the infrastructure service) and `certpost` (the client tool).

## Server

### Setup

Create a data directory and run the interactive setup wizard:

```bash
certpost-server setup -d /var/lib/certpost
```

The wizard prompts for:

- **Base domain** — e.g. `example.com`
- **ACME DNS provider** — the provider used for Let's Encrypt DNS-01 challenges (TXT records)
- **Records DNS provider** — the provider used for A/CNAME records (can be the same or different)
- **Server settings** — bind address and port

For each DNS provider, you'll be asked to choose Cloudflare or Technitium and enter the relevant credentials:

- **Cloudflare** — API token (from Cloudflare profile > API Tokens) and Zone ID (from domain overview page)
- **Technitium** — server URL, API token, and zone name

An admin key is generated automatically. All fields can be skipped and filled in later by editing `config.json`.

### Starting the server

```bash
certpost-server run -d /var/lib/certpost
```

The `--data-dir` (`-d`) flag is required — there is no default location.

### Server options (run)

| Option              | Description                              |
|---------------------|------------------------------------------|
| `--data-dir`, `-d`  | Data directory (required)                |
| `--port`, `-p`      | Port to listen on (default: 8443)        |
| `--host`, `-H`      | Host to bind to (default: 0.0.0.0)       |

### Configuration

The `config.json` in your data directory. Use a single `dns` key when one provider handles everything:

```json
{
  "base_domain": "example.com",
  "admin_key": "auto-generated-login-key",
  "bind": "0.0.0.0",
  "port": 8443,
  "dns": {
    "provider": "cloudflare",
    "api_token": "your-cloudflare-api-token",
    "zone_id": "your-zone-id"
  }
}
```

For split configurations (e.g. Cloudflare for ACME challenges, Technitium for domain records), use `dns_acme` and `dns_records` instead:

```json
{
  "base_domain": "example.com",
  "admin_key": "auto-generated-login-key",
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

| Provider    | Required fields                            |
|-------------|-------------------------------------------|
| cloudflare  | `api_token`, `zone_id`                    |
| technitium  | `server_url`, `api_token`, `zone`         |

Legacy configs with flat `cloudflare_api_token` and `cloudflare_zone_id` keys are automatically migrated on first startup.

### Admin panel

Open `http://localhost:8443` and log in with your admin key (printed on server startup). The admin panel has two tabs:

**Domains** — add subdomains with a target (IP address or CNAME hostname). certpost will:

- Create an A or CNAME record via the configured DNS provider
- Issue a Let's Encrypt certificate via DNS-01 challenge
- Generate a per-domain API token

Each domain card shows:

- Status (pending, issuing, issued, error)
- Target — IP address or CNAME (editable)
- Certificate expiry date
- API token (masked by default, click Show to reveal, Copy to clipboard)
- Download button for `.crt` and `.key` files
- Rotate button to regenerate the API token

**Logs** — real-time server logs showing ACME operations, DNS changes, errors, and certificate issuance progress.

### API

#### Public endpoints (no authentication)

| Endpoint           | Description                                 |
|--------------------|---------------------------------------------|
| `GET /api/version` | Product name, API version, server version   |
| `GET /api/spec`    | OpenAPI 3.0 specification (JSON)            |
| `GET /api/help`    | Human-readable API documentation (text)     |

#### Certificate retrieval (per-domain bearer token)

```
GET /api/cert/<domain>
Authorization: Bearer <per-domain-token>
```

Response:

```json
{
  "cert_pem": "-----BEGIN CERTIFICATE-----\n...",
  "chain_pem": "-----BEGIN CERTIFICATE-----\n...",
  "key_pem": "-----BEGIN RSA PRIVATE KEY-----\n...",
  "expires_at": "2026-06-13T03:45:38+00:00",
  "issued_at": "2026-03-15T04:43:29+00:00"
}
```

#### Token info

```
GET /api/token-info
Authorization: Bearer <per-domain-token>
```

Returns the domain associated with the token:

```json
{
  "domain": "app.example.com"
}
```

## Client

The client has four subcommands. Running `certpost` with no command shows help.

### certpost fetch

Download certificates and save as files.

```bash
# One-shot fetch — domain is resolved from the token
certpost fetch -s http://certpost:8443 -t <token>

# Domain passed explicitly (must match the token's domain)
certpost fetch -s http://certpost:8443 -t <token> -d app.example.com

# Save to a specific directory
certpost fetch -s http://certpost:8443 -t <token> -o /etc/ssl/certs

# Auto-refresh every 24 hours
certpost fetch -s http://certpost:8443 -t <token> --refresh 24

# Using a config file (single or multi-domain)
certpost fetch -c fetch.json
```

#### Fetch options

| Option              | Description                                              |
|---------------------|----------------------------------------------------------|
| `--server`, `-s`    | certpost server URL                                      |
| `--token`, `-t`     | Per-domain API token                                     |
| `--domain`, `-d`    | Domain to fetch certificate for (optional — resolved from token if omitted) |
| `--output-dir`, `-o`| Directory to save files (default: current directory)     |
| `--refresh`         | Re-fetch interval in hours (0 = once, default: 0)        |
| `--config`, `-c`    | JSON config file (alternative to CLI flags)              |

#### Fetch config file format — single domain

```json
{
  "server": "http://certpost:8443",
  "domain": "app.example.com",
  "token": "your-api-token",
  "output_dir": "/etc/ssl/certs",
  "refresh_hours": 24
}
```

#### Fetch config file format — multiple domains

Add a `domains` map to fetch several certificates per cycle. When `domains` is
present, the top-level `domain`/`token` fields are ignored.

```json
{
  "server": "http://certpost:8443",
  "output_dir": "/etc/ssl/certs",
  "refresh_hours": 24,
  "domains": {
    "app.example.com": "token-for-app",
    "api.example.com": "token-for-api"
  }
}
```

Each cycle fetches every listed domain. Individual failures are logged but do
not stop the other fetches or halt the refresh loop.

#### Output files

| File                    | Contents                                     |
|-------------------------|----------------------------------------------|
| `app.example.com.crt`  | Server certificate + intermediate chain (PEM)|
| `app.example.com.key`  | Private key (PEM, mode 0600)                 |

### certpost proxy

TLS termination proxy with SNI routing. Fetches certificates from the server, terminates TLS, and forwards plaintext to backend servers. Certificates are refreshed automatically.

```bash
certpost proxy -c proxy.json
```

#### Proxy options

| Option              | Description                                          |
|---------------------|------------------------------------------------------|
| `--config`, `-c`    | JSON config file (required)                          |
| `--listen`          | Listen address, overrides config (default: 0.0.0.0:443)|

#### Proxy config file format

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

| Field           | Description                                          |
|-----------------|------------------------------------------------------|
| `server`        | certpost server URL                                  |
| `listen`        | Address and port to listen on (or just a port number)|
| `refresh_hours` | How often to re-fetch certificates (default: 24)     |
| `routes`        | Map of domain → backend with per-domain token        |

The proxy:

1. Fetches all certificates on startup
2. Listens for TLS connections
3. Uses SNI to select the correct certificate
4. Forwards decrypted traffic to the backend
5. Refreshes certificates in the background

Certificate data is loaded directly into memory via `tls.X509KeyPair` — no temporary files.

### certpost init

Interactive wizard to generate a config file for `fetch` or `proxy` mode.

```bash
certpost init                    # Generates certpost.json
certpost init -o myconfig.json   # Custom output path
```

The wizard:

- Asks whether you want a fetch or proxy config
- Prompts for the server URL
- For fetch and proxy: prompts for refresh interval and one or more domains (enter an empty token to finish)
- Auto-resolves domains from API tokens (via `/api/token-info`)
- Writes a single-domain config when only one domain is added and a multi-domain form when more are added
- Validates the configuration against the server before saving

### certpost sample-config

Print an example config to stdout — useful when you want a template without
running the interactive wizard.

```bash
certpost sample-config fetch          # single-domain fetch config
certpost sample-config fetch-multi    # multi-domain fetch config
certpost sample-config proxy          # proxy config
certpost sample-config proxy -o proxy.json   # write to file instead
```

| Kind          | Description                                       |
|---------------|---------------------------------------------------|
| `fetch`       | Single-domain fetch config                        |
| `fetch-multi` | Multi-domain fetch config (uses `domains` map)    |
| `proxy`       | TLS termination proxy config                      |

## Security

!!! note
    Private keys are stored in JSON files in the data directory. Protect this directory with appropriate filesystem permissions.

- The admin panel is protected by an admin key login with cookie-based auth
- "Remember me" sets a persistent cookie; without it the cookie expires when the browser closes
- Certificate retrieval uses per-domain bearer tokens (not a shared token)
- The TLS proxy loads certificates directly into memory via `tls.X509KeyPair` — no temp files
- Tokens use lowercase alphanumeric characters only (40 characters)
