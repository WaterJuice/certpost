# ----------------------------------------------------------------------------------------
#   server.py
#   ---------
#
#   HTTP server for certpost. Serves the admin panel (protected by login key),
#   handles API requests for certificate retrieval (per-domain bearer token),
#   and manages subdomains.
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

import http.cookies
import json
import pathlib
import sys
import threading
import traceback
import urllib.parse
from http.server import BaseHTTPRequestHandler
from http.server import HTTPServer
from typing import Any
from .acme import AcmeClient
from .cloudflare import CloudflareClient
from .dns import DnsProvider
from .log import log as _log
from .renewal import RenewalThread
from .storage import Storage

# ----------------------------------------------------------------------------------------
#   Types
# ----------------------------------------------------------------------------------------

type JsonDict = dict[str, Any]

# ----------------------------------------------------------------------------------------
#   Constants
# ----------------------------------------------------------------------------------------

_WEB_DIR = pathlib.Path(__file__).parent / "web"

_API_HELP_TEXT = """\
certpost API
============

GET /api/version
  Returns product name, API version, and server version.
  No authentication required.

GET /api/spec
  Returns the OpenAPI 3.0 specification as JSON.
  No authentication required.

GET /api/help
  This help text.
  No authentication required.

GET /api/token-info
  Returns the domain associated with a bearer token.
  Requires a bearer token in the Authorization header.

  Header:  Authorization: Bearer <token>

  Response:
    domain         - The domain this token is for

GET /api/cert/<domain>
  Returns the certificate, chain, and private key for a domain.
  Requires a domain-specific bearer token in the Authorization header.

  Header:  Authorization: Bearer <token>

  Response:
    cert_pem       - Server certificate (PEM)
    chain_pem      - Intermediate certificate chain (PEM)
    key_pem        - Private key (PEM)
    expires_at     - Certificate expiry (ISO 8601)
    issued_at      - Certificate issue date (ISO 8601)

  Example:
    curl -H "Authorization: Bearer <token>" http://localhost:8443/api/cert/app.example.com
"""

_OPENAPI_SPEC: dict[str, object] = {
    "openapi": "3.0.3",
    "info": {
        "title": "certpost",
        "description": "Let's Encrypt certificate manager API",
        "version": "1.0",
    },
    "paths": {
        "/api/version": {
            "get": {
                "summary": "Server version information",
                "responses": {
                    "200": {
                        "description": "Version info",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "product": {
                                            "type": "string",
                                            "example": "certpost",
                                        },
                                        "api_version": {
                                            "type": "string",
                                            "example": "1.0",
                                        },
                                        "server_version": {
                                            "type": "string",
                                            "example": "1.0.0",
                                        },
                                    },
                                },
                            },
                        },
                    },
                },
            },
        },
        "/api/help": {
            "get": {
                "summary": "Human-readable API help",
                "responses": {
                    "200": {
                        "description": "Plain text help",
                        "content": {"text/plain": {"schema": {"type": "string"}}},
                    },
                },
            },
        },
        "/api/cert/{domain}": {
            "get": {
                "summary": "Retrieve certificate for a domain",
                "parameters": [
                    {
                        "name": "domain",
                        "in": "path",
                        "required": True,
                        "schema": {"type": "string"},
                        "description": "Fully qualified domain name",
                    },
                ],
                "security": [{"bearerAuth": []}],
                "responses": {
                    "200": {
                        "description": "Certificate data",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "cert_pem": {
                                            "type": "string",
                                            "description": "Server certificate (PEM)",
                                        },
                                        "chain_pem": {
                                            "type": "string",
                                            "description": "Intermediate chain (PEM)",
                                        },
                                        "key_pem": {
                                            "type": "string",
                                            "description": "Private key (PEM)",
                                        },
                                        "expires_at": {
                                            "type": "string",
                                            "format": "date-time",
                                            "description": "Certificate expiry",
                                        },
                                        "issued_at": {
                                            "type": "string",
                                            "format": "date-time",
                                            "description": "Certificate issue date",
                                        },
                                    },
                                },
                            },
                        },
                    },
                    "401": {"description": "Missing or invalid Authorization header"},
                    "403": {"description": "Invalid token for this domain"},
                    "404": {"description": "No certificate found for domain"},
                },
            },
        },
    },
    "components": {
        "securitySchemes": {
            "bearerAuth": {
                "type": "http",
                "scheme": "bearer",
                "description": "Domain-specific API token from the certpost admin panel",
            },
        },
    },
}

# ----------------------------------------------------------------------------------------
#   Helpers
# ----------------------------------------------------------------------------------------


# ----------------------------------------------------------------------------------------
def _is_ip_address(value: str) -> bool:
    """Return True if value looks like an IPv4 address, False if it's a hostname."""
    parts = value.split(".")
    if len(parts) != 4:
        return False
    return all(p.isdigit() and 0 <= int(p) <= 255 for p in parts)


# ----------------------------------------------------------------------------------------
def _set_dns_record(dns: DnsProvider, fqdn: str, target: str) -> str:
    """Create the appropriate DNS record (A or CNAME) for the target. Returns the type."""
    if _is_ip_address(target):
        dns.set_a_record(fqdn, target)
        return "A"
    else:
        dns.set_cname_record(fqdn, target)
        return "CNAME"


# ----------------------------------------------------------------------------------------
def _remove_dns_records(dns: DnsProvider, fqdn: str) -> None:
    """Remove both A and CNAME records for a domain."""
    dns.remove_a_record(fqdn)
    dns.remove_cname_record(fqdn)


# ----------------------------------------------------------------------------------------
#   Module State
# ----------------------------------------------------------------------------------------

_storage: Storage | None = None
_acme_client: AcmeClient | None = None
_dns_client: DnsProvider | None = None
_renewal_thread: RenewalThread | None = None

# ----------------------------------------------------------------------------------------
#   Request Handler
# ----------------------------------------------------------------------------------------


# ----------------------------------------------------------------------------------------
class _CertpostHandler(BaseHTTPRequestHandler):
    """HTTP request handler for certpost admin panel and API."""

    # ------------------------------------------------------------------------------------
    #   Logging
    # ------------------------------------------------------------------------------------

    # ------------------------------------------------------------------------------------
    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        """Log HTTP requests to stderr."""
        print(f"  [http] {self.address_string()} - {format % args}", file=sys.stderr)

    # ------------------------------------------------------------------------------------
    #   Auth helpers
    # ------------------------------------------------------------------------------------

    # ------------------------------------------------------------------------------------
    def _is_admin_authenticated(self) -> bool:
        """Check if the request has a valid admin cookie."""
        assert _storage is not None
        cookie_header = self.headers.get("Cookie", "")
        cookies = http.cookies.SimpleCookie(cookie_header)  # pyright: ignore[reportMissingTypeArgument]
        session = cookies.get("certpost_session")
        if session is None:
            return False
        return _storage.verify_admin_cookie(session.value)

    # ------------------------------------------------------------------------------------
    def _require_admin(self) -> bool:
        """Check admin auth; send 401 if not authenticated. Returns True if OK."""
        if not self._is_admin_authenticated():
            self._send_error(401, "Not authenticated")
            return False
        return True

    # ------------------------------------------------------------------------------------
    #   GET routes
    # ------------------------------------------------------------------------------------

    # ------------------------------------------------------------------------------------
    def do_GET(self) -> None:
        """Handle GET requests."""
        path = self.path.split("?")[0]

        # Public routes
        if path == "/" or path == "/index.html":
            self._serve_admin_panel()
        elif path == "/api/version":
            self._handle_get_version()
        elif path == "/api/spec":
            self._handle_get_spec()
        elif path == "/api/help":
            self._handle_get_help()
        elif path == "/api/token-info":
            self._handle_token_info()
        elif path.startswith("/api/cert/"):
            self._handle_get_cert(path)
        # Admin routes (require session)
        elif path == "/api/domains":
            if self._require_admin():
                self._handle_get_domains()
        elif path == "/api/base-domain":
            if self._require_admin():
                self._handle_get_base_domain()
        elif path == "/api/logs":
            if self._require_admin():
                self._handle_get_logs()
        elif path == "/api/auth/check":
            self._handle_auth_check()
        else:
            self._send_error(404, "Not found")

    # ------------------------------------------------------------------------------------
    #   POST routes
    # ------------------------------------------------------------------------------------

    # ------------------------------------------------------------------------------------
    def do_POST(self) -> None:
        """Handle POST requests."""
        path = self.path.split("?")[0]

        # Login route (no session required)
        if path == "/api/auth/login":
            self._handle_login()
        # Admin routes (require session)
        elif path == "/api/domains":
            if self._require_admin():
                self._handle_add_domain()
        elif path.startswith("/api/domains/") and path.endswith("/rotate"):
            if self._require_admin():
                subdomain = path[len("/api/domains/") : -len("/rotate")]
                self._handle_rotate_token(subdomain)
        elif path.startswith("/api/domains/") and path.endswith("/target"):
            if self._require_admin():
                subdomain = path[len("/api/domains/") : -len("/target")]
                self._handle_update_target(subdomain)
        else:
            self._send_error(404, "Not found")

    # ------------------------------------------------------------------------------------
    #   DELETE routes
    # ------------------------------------------------------------------------------------

    # ------------------------------------------------------------------------------------
    def do_DELETE(self) -> None:
        """Handle DELETE requests."""
        path = self.path.split("?")[0]

        if path.startswith("/api/domains/"):
            if self._require_admin():
                subdomain = path[len("/api/domains/") :]
                self._handle_remove_domain(subdomain)
        else:
            self._send_error(404, "Not found")

    # ------------------------------------------------------------------------------------
    #   Admin panel
    # ------------------------------------------------------------------------------------

    # ------------------------------------------------------------------------------------
    def _serve_admin_panel(self) -> None:
        """Serve the admin panel HTML."""
        html_path = _WEB_DIR / "index.html"
        if not html_path.exists():
            self._send_error(500, "Admin panel not found")
            return

        content = html_path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(content)

    # ------------------------------------------------------------------------------------
    #   Auth handlers
    # ------------------------------------------------------------------------------------

    # ------------------------------------------------------------------------------------
    def _handle_login(self) -> None:
        """Handle admin login — verify key and set session cookie."""
        assert _storage is not None
        body = self._read_body()
        if body is None:
            return

        key = body.get("key", "")
        if not _storage.verify_admin_key(key):
            self._send_error(403, "Invalid admin key")
            return

        remember = body.get("remember", False)
        cookie_value = _storage.admin_cookie_value()

        response_body = json.dumps({"status": "ok"}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(response_body)))
        # Persistent cookie (30 days) if remember, otherwise session cookie
        cookie = f"certpost_session={cookie_value}; Path=/; HttpOnly; SameSite=Strict"
        if remember:
            cookie += "; Max-Age=2592000"
        self.send_header("Set-Cookie", cookie)
        self.end_headers()
        self.wfile.write(response_body)

    # ------------------------------------------------------------------------------------
    def _handle_auth_check(self) -> None:
        """Check if the current session is valid."""
        if self._is_admin_authenticated():
            self._send_json({"authenticated": True})
        else:
            self._send_json({"authenticated": False})

    # ------------------------------------------------------------------------------------
    #   API handlers — domains
    # ------------------------------------------------------------------------------------

    # ------------------------------------------------------------------------------------
    def _handle_get_domains(self) -> None:
        """Return the list of managed domains."""
        assert _storage is not None
        domains = _storage.get_domains()
        self._send_json({"domains": domains})

    # ------------------------------------------------------------------------------------
    def _handle_get_base_domain(self) -> None:
        """Return the base domain from config."""
        assert _storage is not None
        config = _storage.get_config()
        self._send_json({"base_domain": config.get("base_domain", "")})

    # ------------------------------------------------------------------------------------
    def _handle_add_domain(self) -> None:
        """Add a new subdomain and start certificate issuance."""
        assert _storage is not None
        assert _acme_client is not None

        body = self._read_body()
        if body is None:
            return

        subdomain = body.get("subdomain", "")
        target = body.get("target", "")
        if not subdomain:
            self._send_error(400, "Missing subdomain")
            return
        if not target:
            self._send_error(400, "Missing target")
            return

        config = _storage.get_config()
        base_domain = str(config.get("base_domain", ""))
        if not base_domain:
            self._send_error(400, "Base domain not configured")
            return

        fqdn = (
            f"{subdomain}.{base_domain}"
            if not subdomain.endswith(base_domain)
            else subdomain
        )

        entry = _storage.add_domain(fqdn, target)
        self._send_json(entry)

        # Create DNS record and issue certificate in background thread
        acme = _acme_client
        cf = _dns_client
        storage = _storage

        def _setup() -> None:
            try:
                # Create A or CNAME record
                assert cf is not None
                record_type = _set_dns_record(cf, fqdn, target)
                _log("server", f"{record_type} record created: {fqdn} -> {target}")
                # Issue certificate
                acme.issue_certificate(fqdn)
            except Exception as e:
                error_msg = f"{type(e).__name__}: {e}"
                _log("server", f"Setup failed for {fqdn}: {error_msg}")
                storage.update_domain(
                    fqdn, {"status": "error", "last_error": error_msg}
                )

        threading.Thread(target=_setup, daemon=True, name=f"setup-{fqdn}").start()

    # ------------------------------------------------------------------------------------
    def _handle_remove_domain(self, subdomain: str) -> None:
        """Remove a subdomain and its DNS records."""
        assert _storage is not None
        subdomain = urllib.parse.unquote(subdomain)

        # Remove DNS records (both A and CNAME)
        if _dns_client is not None:
            try:
                _remove_dns_records(_dns_client, subdomain)
            except Exception as e:
                _log("server", f"Failed to remove DNS records for {subdomain}: {e}")

        _storage.remove_domain(subdomain)
        self._send_json({"status": "removed"})

    # ------------------------------------------------------------------------------------
    def _handle_update_target(self, subdomain: str) -> None:
        """Update the DNS target (IP address or CNAME) for a domain."""
        assert _storage is not None
        subdomain = urllib.parse.unquote(subdomain)

        body = self._read_body()
        if body is None:
            return

        target = body.get("target", "")
        if not target:
            self._send_error(400, "Missing target")
            return

        # Remove old records and create new one
        if _dns_client is not None:
            try:
                _remove_dns_records(_dns_client, subdomain)
                record_type = _set_dns_record(_dns_client, subdomain, target)
                _log("server", f"{record_type} record updated: {subdomain} -> {target}")
            except Exception as e:
                self._send_error(500, f"Failed to update DNS: {e}")
                return

        _storage.update_domain(subdomain, {"target": target})
        self._send_json({"status": "updated", "target": target})

    # ------------------------------------------------------------------------------------
    def _handle_rotate_token(self, subdomain: str) -> None:
        """Rotate the API token for a domain."""
        assert _storage is not None
        subdomain = urllib.parse.unquote(subdomain)
        new_token = _storage.rotate_domain_token(subdomain)
        self._send_json({"subdomain": subdomain, "api_token": new_token})

    # ------------------------------------------------------------------------------------
    #   API handlers — info
    # ------------------------------------------------------------------------------------

    # ------------------------------------------------------------------------------------
    def _handle_get_logs(self) -> None:
        """Return recent log entries."""
        from .log import get_entries

        self._send_json({"entries": get_entries()})

    # ------------------------------------------------------------------------------------
    def _handle_get_version(self) -> None:
        """Return product name, API version, and server version."""
        from .version import VERSION_STR

        self._send_json(
            {
                "product": "certpost",
                "api_version": "1.0",
                "server_version": VERSION_STR,
            }
        )

    # ------------------------------------------------------------------------------------
    def _handle_get_spec(self) -> None:
        """Return OpenAPI spec."""
        self._send_json(_OPENAPI_SPEC)

    # ------------------------------------------------------------------------------------
    def _handle_get_help(self) -> None:
        """Return human-readable API help."""
        self._send_text(_API_HELP_TEXT)

    # ------------------------------------------------------------------------------------
    def _handle_token_info(self) -> None:
        """Return the domain associated with a bearer token."""
        assert _storage is not None

        auth_header = self.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            self._send_error(401, "Missing or invalid Authorization header")
            return

        token = auth_header[7:]
        domains = _storage.get_domains()
        for d in domains:
            if d.get("api_token") == token:
                self._send_json({"domain": d.get("subdomain", "")})
                return

        self._send_error(403, "Invalid token")

    # ------------------------------------------------------------------------------------
    #   API handlers — certificate retrieval (per-domain bearer auth)
    # ------------------------------------------------------------------------------------

    # ------------------------------------------------------------------------------------
    def _handle_get_cert(self, path: str) -> None:
        """Return certificate data for a subdomain (requires domain-specific bearer token)."""
        assert _storage is not None

        # Authenticate
        auth_header = self.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            self._send_error(401, "Missing or invalid Authorization header")
            return

        token = auth_header[7:]
        subdomain = path[len("/api/cert/") :]
        if not subdomain:
            self._send_error(400, "Missing subdomain")
            return

        subdomain = urllib.parse.unquote(subdomain)

        if not _storage.verify_domain_token(subdomain, token):
            self._send_error(403, "Invalid token for this domain")
            return

        cert = _storage.get_cert(subdomain)
        if cert is None:
            self._send_error(404, f"No certificate found for {subdomain}")
            return

        self._send_json(cert)

    # ------------------------------------------------------------------------------------
    #   Helpers
    # ------------------------------------------------------------------------------------

    # ------------------------------------------------------------------------------------
    def _read_body(self) -> JsonDict | None:
        """Read and parse the JSON request body."""
        try:
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length)
            return json.loads(raw)  # pyright: ignore[reportReturnType]
        except (ValueError, json.JSONDecodeError) as e:
            self._send_error(400, f"Invalid JSON: {e}")
            return None

    # ------------------------------------------------------------------------------------
    def _send_json(self, data: Any, code: int = 200) -> None:
        """Send a JSON response with indent=2 and trailing newline."""
        body = (json.dumps(data, indent=2) + "\n").encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # ------------------------------------------------------------------------------------
    def _send_text(self, text: str, code: int = 200) -> None:
        """Send a plain text response."""
        body = text.encode()
        self.send_response(code)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # ------------------------------------------------------------------------------------
    def _send_error(self, code: int, message: str) -> None:
        """Send a JSON error response."""
        self._send_json({"error": message}, code=code)


# ----------------------------------------------------------------------------------------
#   Server
# ----------------------------------------------------------------------------------------


# ----------------------------------------------------------------------------------------
def run_server(host: str, port: int, data_dir: str) -> None:
    """Start the certpost HTTP server."""
    global _storage, _acme_client, _dns_client, _renewal_thread

    _storage = Storage(data_dir)

    # Print admin key on startup so operator can find it
    config = _storage.get_config()
    admin_key = config.get("admin_key", "")
    print(f"  Admin key: {admin_key}", file=sys.stderr)

    # Initialise DNS client (Cloudflare)
    dns: DnsProvider = CloudflareClient(
        api_token=str(config.get("cloudflare_api_token", "")),
        zone_id=str(config.get("cloudflare_zone_id", "")),
    )
    _dns_client = dns

    # Initialise ACME client
    _acme_client = AcmeClient(_storage, dns)
    try:
        _acme_client.initialise()
    except Exception:
        _log(
            "server", f"Warning: ACME initialisation failed:\n{traceback.format_exc()}"
        )
        _log(
            "server", "Certificate operations will not work until config is corrected."
        )

    # Start renewal thread
    _renewal_thread = RenewalThread(_storage, _acme_client)
    _renewal_thread.start()

    # Start HTTP server
    server = HTTPServer((host, port), _CertpostHandler)
    server.daemon_threads = True  # pyright: ignore[reportAttributeAccessIssue]

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        _renewal_thread.stop()
        server.server_close()
