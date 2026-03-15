# ----------------------------------------------------------------------------------------
#   server.py
#   ---------
#
#   HTTP server for certpost. Serves the admin panel, handles API requests for
#   certificate retrieval (bearer token auth), and manages subdomains and tokens.
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

import json
import pathlib
import sys
import threading
import traceback
from http.server import BaseHTTPRequestHandler
from http.server import HTTPServer
from typing import Any
from .acme import AcmeClient
from .cloudflare import CloudflareClient
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
    #   GET routes
    # ------------------------------------------------------------------------------------

    # ------------------------------------------------------------------------------------
    def do_GET(self) -> None:
        """Handle GET requests."""
        path = self.path.split("?")[0]

        if path == "/" or path == "/index.html":
            self._serve_admin_panel()
        elif path == "/api/domains":
            self._handle_get_domains()
        elif path == "/api/tokens":
            self._handle_get_tokens()
        elif path == "/api/config":
            self._handle_get_config()
        elif path.startswith("/api/cert/"):
            self._handle_get_cert(path)
        else:
            self._send_error(404, "Not found")

    # ------------------------------------------------------------------------------------
    #   POST routes
    # ------------------------------------------------------------------------------------

    # ------------------------------------------------------------------------------------
    def do_POST(self) -> None:
        """Handle POST requests."""
        path = self.path.split("?")[0]

        if path == "/api/domains":
            self._handle_add_domain()
        elif path == "/api/tokens":
            self._handle_create_token()
        elif path == "/api/config":
            self._handle_save_config()
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
            subdomain = path[len("/api/domains/") :]
            self._handle_remove_domain(subdomain)
        elif path.startswith("/api/tokens/"):
            token_hash = path[len("/api/tokens/") :]
            self._handle_revoke_token(token_hash)
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
    #   API handlers — domains
    # ------------------------------------------------------------------------------------

    # ------------------------------------------------------------------------------------
    def _handle_get_domains(self) -> None:
        """Return the list of managed domains."""
        assert _storage is not None
        domains = _storage.get_domains()
        self._send_json({"domains": domains})

    # ------------------------------------------------------------------------------------
    def _handle_add_domain(self) -> None:
        """Add a new subdomain and start certificate issuance."""
        assert _storage is not None
        assert _acme_client is not None

        body = self._read_body()
        if body is None:
            return

        subdomain = body.get("subdomain", "")
        if not subdomain:
            self._send_error(400, "Missing subdomain")
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

        entry = _storage.add_domain(fqdn)
        self._send_json(entry)

        # Issue certificate in background thread
        acme = _acme_client
        storage = _storage

        def _issue() -> None:
            try:
                acme.issue_certificate(fqdn)
            except Exception as e:
                error_msg = f"{type(e).__name__}: {e}"
                print(
                    f"  [server] Cert issuance failed for {fqdn}: {error_msg}",
                    file=sys.stderr,
                )
                storage.update_domain(
                    fqdn, {"status": "error", "last_error": error_msg}
                )

        threading.Thread(target=_issue, daemon=True, name=f"issue-{fqdn}").start()

    # ------------------------------------------------------------------------------------
    def _handle_remove_domain(self, subdomain: str) -> None:
        """Remove a subdomain from management."""
        assert _storage is not None
        _storage.remove_domain(subdomain)
        self._send_json({"status": "removed"})

    # ------------------------------------------------------------------------------------
    #   API handlers — tokens
    # ------------------------------------------------------------------------------------

    # ------------------------------------------------------------------------------------
    def _handle_get_tokens(self) -> None:
        """Return the list of API tokens (without hashes exposed in full)."""
        assert _storage is not None
        tokens = _storage.get_tokens()
        # Only return label, partial hash, and created_at
        safe_tokens: list[JsonDict] = []
        for t in tokens:
            safe_tokens.append(
                {
                    "label": t.get("label", ""),
                    "hash": t.get("hash", ""),
                    "hash_prefix": str(t.get("hash", ""))[:8],
                    "created_at": t.get("created_at"),
                }
            )
        self._send_json({"tokens": safe_tokens})

    # ------------------------------------------------------------------------------------
    def _handle_create_token(self) -> None:
        """Create a new API token."""
        assert _storage is not None
        body = self._read_body()
        if body is None:
            return

        label = body.get("label", "")
        if not label:
            self._send_error(400, "Missing label")
            return

        token = _storage.create_token(label)
        self._send_json({"token": token, "label": label})

    # ------------------------------------------------------------------------------------
    def _handle_revoke_token(self, token_hash: str) -> None:
        """Revoke an API token."""
        assert _storage is not None
        _storage.revoke_token(token_hash)
        self._send_json({"status": "revoked"})

    # ------------------------------------------------------------------------------------
    #   API handlers — config
    # ------------------------------------------------------------------------------------

    # ------------------------------------------------------------------------------------
    def _handle_get_config(self) -> None:
        """Return the current configuration (with API token masked)."""
        assert _storage is not None
        config = _storage.get_config()
        # Mask the API token
        if config.get("cloudflare_api_token"):
            token = str(config["cloudflare_api_token"])
            config["cloudflare_api_token"] = (
                token[:4] + "****" + token[-4:] if len(token) > 8 else "****"
            )
        self._send_json(config)

    # ------------------------------------------------------------------------------------
    def _handle_save_config(self) -> None:
        """Update configuration."""
        assert _storage is not None
        body = self._read_body()
        if body is None:
            return

        # Merge with existing config, don't overwrite API token if masked
        config = _storage.get_config()
        for key, value in body.items():
            if key == "cloudflare_api_token" and "****" in str(value):
                continue
            config[key] = value

        _storage.save_config(config)
        self._send_json({"status": "saved"})

    # ------------------------------------------------------------------------------------
    #   API handlers — certificate retrieval (bearer auth)
    # ------------------------------------------------------------------------------------

    # ------------------------------------------------------------------------------------
    def _handle_get_cert(self, path: str) -> None:
        """Return certificate data for a subdomain (requires bearer token)."""
        assert _storage is not None

        # Authenticate
        auth_header = self.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            self._send_error(401, "Missing or invalid Authorization header")
            return

        token = auth_header[7:]
        if not _storage.verify_token(token):
            self._send_error(403, "Invalid token")
            return

        subdomain = path[len("/api/cert/") :]
        if not subdomain:
            self._send_error(400, "Missing subdomain")
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
    global _storage, _acme_client, _renewal_thread

    _storage = Storage(data_dir)

    # Initialise Cloudflare client from config
    config = _storage.get_config()
    cloudflare = CloudflareClient(
        api_token=str(config.get("cloudflare_api_token", "")),
        zone_id=str(config.get("cloudflare_zone_id", "")),
    )

    # Initialise ACME client
    _acme_client = AcmeClient(_storage, cloudflare)
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
