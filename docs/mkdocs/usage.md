# Usage

certpost has two commands: `certpost-server` (the infrastructure service) and `certpost` (the client tool).

## Server

### Setup

Create a data directory and run the interactive setup wizard:

```bash
certpost-server setup -d /var/lib/certpost
```

The wizard prompts for:

- **Cloudflare API token** — from your Cloudflare profile > API Tokens (use the "Edit zone DNS" template)
- **Cloudflare Zone ID** — from your domain's overview page in Cloudflare
- **Base domain** — e.g. `example.com`
- **Port** — default `8443`

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

The `config.json` in your data directory:

```json
{
  "cloudflare_api_token": "your-cloudflare-api-token",
  "cloudflare_zone_id": "your-zone-id",
  "base_domain": "example.com",
  "admin_key": "auto-generated-login-key",
  "bind": "0.0.0.0",
  "port": 8443
}
```

### Admin panel

Open `http://localhost:8443` and log in with your admin key (printed on server startup). The admin panel has two tabs:

**Domains** — add subdomains with an IP address. certpost will:

- Create an A record in Cloudflare pointing to that IP
- Issue a Let's Encrypt certificate via DNS-01 challenge
- Generate a per-domain API token

Each domain card shows:

- Status (pending, issuing, issued, error)
- IP address (editable)
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

The client has three subcommands. Running `certpost` with no command shows help.

### certpost fetch

Download certificates and save as files.

```bash
# One-shot fetch using CLI args
certpost fetch -s http://certpost:8443 -t <token> -d app.example.com

# Save to a specific directory
certpost fetch -s http://certpost:8443 -t <token> -d app.example.com -o /etc/ssl/certs

# Auto-refresh every 24 hours
certpost fetch -s http://certpost:8443 -t <token> -d app.example.com --refresh 24

# Using a config file
certpost fetch -c fetch.json
```

#### Fetch options

| Option              | Description                                              |
|---------------------|----------------------------------------------------------|
| `--server`, `-s`    | certpost server URL                                      |
| `--token`, `-t`     | Per-domain API token                                     |
| `--domain`, `-d`    | Domain to fetch certificate for                          |
| `--output-dir`, `-o`| Directory to save files (default: current directory)     |
| `--refresh`         | Re-fetch interval in hours (0 = once, default: 0)        |
| `--config`, `-c`    | JSON config file (alternative to CLI flags)              |

#### Fetch config file format

```json
{
  "server": "http://certpost:8443",
  "domain": "app.example.com",
  "token": "your-api-token",
  "output_dir": "/etc/ssl/certs",
  "refresh_hours": 24
}
```

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

Certificate data is loaded into OpenSSL's memory. Temporary files used during loading are deleted immediately.

### certpost init

Interactive wizard to generate a config file for `fetch` or `proxy` mode.

```bash
certpost init                    # Generates certpost.json
certpost init -o myconfig.json   # Custom output path
```

The wizard:

- Asks whether you want a fetch or proxy config
- Prompts for the server URL
- For proxy: prompts for listen address, refresh interval, and routes
- Auto-resolves domains from API tokens (via `/api/token-info`)
- Validates the configuration against the server before saving

## Running as a module

```bash
python -m certpost fetch -s http://certpost:8443 -t <token> -d app.example.com
```

## Security

!!! note
    Private keys are stored in JSON files in the data directory. Protect this directory with appropriate filesystem permissions.

- The admin panel is protected by an admin key login with cookie-based auth
- "Remember me" sets a persistent cookie; without it the cookie expires when the browser closes
- Certificate retrieval uses per-domain bearer tokens (not a shared token)
- The TLS proxy loads certificates into memory and immediately deletes temporary files
- Tokens use lowercase alphanumeric characters only (40 characters)
