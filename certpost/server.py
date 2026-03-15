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
        """Check if the request has a valid admin session cookie."""
        assert _storage is not None
        cookie_header = self.headers.get("Cookie", "")
        cookies = http.cookies.SimpleCookie(cookie_header)  # pyright: ignore[reportMissingTypeArgument]
        session = cookies.get("certpost_session")
        if session is None:
            return False
        return _storage.verify_session(session.value)

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
        elif path.startswith("/api/cert/"):
            self._handle_get_cert(path)
        # Admin routes (require session)
        elif path == "/api/domains":
            if self._require_admin():
                self._handle_get_domains()
        elif path == "/api/base-domain":
            if self._require_admin():
                self._handle_get_base_domain()
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
        elif path.startswith("/api/domains/") and path.endswith("/ip"):
            if self._require_admin():
                subdomain = path[len("/api/domains/") : -len("/ip")]
                self._handle_update_ip(subdomain)
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
        session_token = _storage.create_session()

        response_body = json.dumps({"status": "ok"}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(response_body)))
        # Persistent cookie (1 year) if remember, otherwise session cookie
        cookie = f"certpost_session={session_token}; Path=/; HttpOnly; SameSite=Strict"
        if remember:
            cookie += "; Max-Age=31536000"
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
        ip_address = body.get("ip_address", "")
        if not subdomain:
            self._send_error(400, "Missing subdomain")
            return
        if not ip_address:
            self._send_error(400, "Missing IP address")
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

        entry = _storage.add_domain(fqdn, ip_address)
        self._send_json(entry)

        # Create A record and issue certificate in background thread
        acme = _acme_client
        cf = _dns_client
        storage = _storage

        def _setup() -> None:
            try:
                # Create A record
                assert cf is not None
                cf.set_a_record(fqdn, ip_address)
                print(
                    f"  [server] A record created: {fqdn} -> {ip_address}",
                    file=sys.stderr,
                )
                # Issue certificate
                acme.issue_certificate(fqdn)
            except Exception as e:
                error_msg = f"{type(e).__name__}: {e}"
                print(
                    f"  [server] Setup failed for {fqdn}: {error_msg}",
                    file=sys.stderr,
                )
                storage.update_domain(
                    fqdn, {"status": "error", "last_error": error_msg}
                )

        threading.Thread(target=_setup, daemon=True, name=f"setup-{fqdn}").start()

    # ------------------------------------------------------------------------------------
    def _handle_remove_domain(self, subdomain: str) -> None:
        """Remove a subdomain and its A record."""
        assert _storage is not None
        subdomain = urllib.parse.unquote(subdomain)

        # Remove A record from DNS
        if _dns_client is not None:
            try:
                _dns_client.remove_a_record(subdomain)
            except Exception as e:
                print(
                    f"  [server] Failed to remove A record for {subdomain}: {e}",
                    file=sys.stderr,
                )

        _storage.remove_domain(subdomain)
        self._send_json({"status": "removed"})

    # ------------------------------------------------------------------------------------
    def _handle_update_ip(self, subdomain: str) -> None:
        """Update the IP address for a domain."""
        assert _storage is not None
        subdomain = urllib.parse.unquote(subdomain)

        body = self._read_body()
        if body is None:
            return

        ip_address = body.get("ip_address", "")
        if not ip_address:
            self._send_error(400, "Missing IP address")
            return

        # Update A record in DNS
        if _dns_client is not None:
            try:
                _dns_client.set_a_record(subdomain, ip_address)
                print(
                    f"  [server] A record updated: {subdomain} -> {ip_address}",
                    file=sys.stderr,
                )
            except Exception as e:
                self._send_error(500, f"Failed to update DNS: {e}")
                return

        _storage.update_domain(subdomain, {"ip_address": ip_address})
        self._send_json({"status": "updated", "ip_address": ip_address})

    # ------------------------------------------------------------------------------------
    def _handle_rotate_token(self, subdomain: str) -> None:
        """Rotate the API token for a domain."""
        assert _storage is not None
        subdomain = urllib.parse.unquote(subdomain)
        new_token = _storage.rotate_domain_token(subdomain)
        self._send_json({"subdomain": subdomain, "api_token": new_token})

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
    def _send_json(self, data: Any) -> None:
        """Send a JSON response."""
        body = json.dumps(data, indent=2).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # ------------------------------------------------------------------------------------
    def _send_error(self, code: int, message: str) -> None:
        """Send a JSON error response."""
        body = json.dumps({"error": message}).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


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
        print(
            f"  [server] Warning: ACME initialisation failed:\n{traceback.format_exc()}",
            file=sys.stderr,
        )
        print(
            "  [server] Certificate operations will not work until config is corrected.",
            file=sys.stderr,
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
