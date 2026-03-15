# ----------------------------------------------------------------------------------------
#   proxy.py
#   --------
#
#   TLS termination proxy with SNI-based routing. Fetches certificates from a
#   certpost server, terminates TLS, and forwards plaintext to backend servers.
#   Certificates are refreshed automatically on a configurable interval.
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

import pathlib
import socket
import ssl
import sys
import tempfile
import threading
import traceback
from typing import Any
from .client_fetch import fetch_cert

# ----------------------------------------------------------------------------------------
#   Types
# ----------------------------------------------------------------------------------------

type JsonDict = dict[str, Any]

# ----------------------------------------------------------------------------------------
#   Constants
# ----------------------------------------------------------------------------------------

_DEFAULT_REFRESH_HOURS = 24
_BUFFER_SIZE = 65536

# ----------------------------------------------------------------------------------------
#   Certificate Store
# ----------------------------------------------------------------------------------------


# ----------------------------------------------------------------------------------------
class _CertStore:
    """Thread-safe store for domain certificates and SSL contexts."""

    # ------------------------------------------------------------------------------------
    def __init__(self) -> None:
        """Initialise the certificate store."""
        self._lock = threading.Lock()
        self._contexts: dict[str, ssl.SSLContext] = {}
        self.cert_dir = pathlib.Path(tempfile.mkdtemp(prefix="certpost-proxy-"))

    # ------------------------------------------------------------------------------------
    def update_cert(self, domain: str, cert_data: JsonDict) -> None:
        """Update the certificate for a domain."""
        cert_pem = str(cert_data.get("cert_pem", ""))
        chain_pem = str(cert_data.get("chain_pem", ""))
        key_pem = str(cert_data.get("key_pem", ""))

        domain_dir = self.cert_dir / domain
        domain_dir.mkdir(parents=True, exist_ok=True)

        cert_path = domain_dir / "cert.pem"
        key_path = domain_dir / "key.pem"
        cert_path.write_text(cert_pem + chain_pem)
        key_path.write_text(key_pem)
        key_path.chmod(0o600)

        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(str(cert_path), str(key_path))
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2

        with self._lock:
            self._contexts[domain] = ctx

        print(f"  [proxy] Certificate loaded for {domain}", file=sys.stderr)

    # ------------------------------------------------------------------------------------
    def get_context(self, domain: str) -> ssl.SSLContext | None:
        """Get the SSL context for a domain."""
        with self._lock:
            return self._contexts.get(domain)

    # ------------------------------------------------------------------------------------
    def has_domain(self, domain: str) -> bool:
        """Check if a domain has a certificate loaded."""
        with self._lock:
            return domain in self._contexts


# ----------------------------------------------------------------------------------------
#   Certificate Refresher
# ----------------------------------------------------------------------------------------


# ----------------------------------------------------------------------------------------
class _CertRefresher:
    """Background thread that periodically refreshes certificates."""

    # ------------------------------------------------------------------------------------
    def __init__(
        self,
        cert_store: _CertStore,
        server_url: str,
        routes: dict[str, JsonDict],
        refresh_hours: int,
    ) -> None:
        """Initialise the refresher."""
        self._cert_store = cert_store
        self._server_url = server_url
        self._routes = routes
        self._refresh_seconds = refresh_hours * 3600
        self._stop_event = threading.Event()

    # ------------------------------------------------------------------------------------
    def start(self) -> None:
        """Start the refresh thread."""
        thread = threading.Thread(target=self._run, daemon=True, name="cert-refresh")
        thread.start()

    # ------------------------------------------------------------------------------------
    def stop(self) -> None:
        """Signal the refresh thread to stop."""
        self._stop_event.set()

    # ------------------------------------------------------------------------------------
    def fetch_all(self) -> None:
        """Fetch all certificates immediately."""
        for domain, route in self._routes.items():
            token = str(route.get("token", ""))
            try:
                cert_data = fetch_cert(self._server_url, token, domain)
                self._cert_store.update_cert(domain, cert_data)
            except Exception:
                print(
                    f"  [proxy] Failed to fetch cert for {domain}:\n{traceback.format_exc()}",
                    file=sys.stderr,
                )

    # ------------------------------------------------------------------------------------
    def _run(self) -> None:
        """Main loop — sleep then refresh."""
        while not self._stop_event.is_set():
            if self._stop_event.wait(self._refresh_seconds):
                return
            print("  [proxy] Refreshing certificates...", file=sys.stderr)
            self.fetch_all()


# ----------------------------------------------------------------------------------------
#   Proxy Server
# ----------------------------------------------------------------------------------------


# ----------------------------------------------------------------------------------------
def _forward(client_sock: socket.socket, backend_addr: str) -> None:
    """Forward data between client and backend."""
    host, port_str = backend_addr.rsplit(":", 1)
    port = int(port_str)

    backend_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        backend_sock.connect((host, port))
    except OSError as e:
        print(
            f"  [proxy] Backend connection failed ({backend_addr}): {e}",
            file=sys.stderr,
        )
        client_sock.close()
        backend_sock.close()
        return

    def _pipe(src: socket.socket, dst: socket.socket) -> None:
        try:
            while True:
                data = src.recv(_BUFFER_SIZE)
                if not data:
                    break
                dst.sendall(data)
        except OSError:
            pass
        finally:
            try:
                dst.shutdown(socket.SHUT_WR)
            except OSError:
                pass

    t1 = threading.Thread(target=_pipe, args=(client_sock, backend_sock), daemon=True)
    t2 = threading.Thread(target=_pipe, args=(backend_sock, client_sock), daemon=True)
    t1.start()
    t2.start()
    t1.join()
    t2.join()
    client_sock.close()
    backend_sock.close()


# ----------------------------------------------------------------------------------------
def run_proxy(config: JsonDict, listen_addr: str) -> None:
    """Start the TLS termination proxy."""
    server_url = str(config.get("server", ""))
    if not server_url:
        print("Error: 'server' is required in config", file=sys.stderr)
        sys.exit(1)

    routes: dict[str, JsonDict] = config.get("routes", {})  # pyright: ignore[reportAssignmentType]
    if not routes:
        print("Error: 'routes' is required in config", file=sys.stderr)
        sys.exit(1)

    refresh_hours = int(config.get("refresh_hours", _DEFAULT_REFRESH_HOURS))

    # Parse listen address
    if ":" in listen_addr:
        host, port_str = listen_addr.rsplit(":", 1)
        port = int(port_str)
    else:
        host = "0.0.0.0"
        port = int(listen_addr)

    # Build route lookup
    backend_map: dict[str, str] = {}
    for domain, route in routes.items():
        backend = str(route.get("backend", ""))
        if not backend:
            print(f"Error: 'backend' is required for route '{domain}'", file=sys.stderr)
            sys.exit(1)
        backend_map[domain] = backend

    # Initialise cert store and fetch initial certs
    cert_store = _CertStore()
    refresher = _CertRefresher(cert_store, server_url, routes, refresh_hours)

    print("  [proxy] Fetching initial certificates...", file=sys.stderr)
    refresher.fetch_all()

    # Check that at least one cert loaded
    loaded = [d for d in routes if cert_store.has_domain(d)]
    if not loaded:
        print("Error: no certificates could be loaded", file=sys.stderr)
        sys.exit(1)

    # Start background refresh
    refresher.start()

    # SNI callback — capture the server name for routing
    _last_sni: list[str] = [""]

    def _sni_callback(
        ssl_socket: ssl.SSLObject, server_name: str | None, _ctx: ssl.SSLContext
    ) -> int | None:
        _last_sni[0] = server_name or ""
        if server_name and cert_store.has_domain(server_name):
            new_ctx = cert_store.get_context(server_name)
            if new_ctx:
                ssl_socket.context = new_ctx
        return None

    # Create base SSL context (will be replaced by SNI callback)
    base_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    base_ctx.sni_callback = _sni_callback  # pyright: ignore[reportAttributeAccessIssue]
    base_ctx.minimum_version = ssl.TLSVersion.TLSv1_2

    # Load first available cert as default
    first_domain = loaded[0]
    first_ctx = cert_store.get_context(first_domain)
    if first_ctx:
        # Copy cert from first context to base
        cert_dir = cert_store.cert_dir / first_domain
        base_ctx.load_cert_chain(str(cert_dir / "cert.pem"), str(cert_dir / "key.pem"))

    # Start listening
    server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        server_sock.bind((host, port))
    except OSError as e:
        print(f"Error: could not bind to {host}:{port} — {e}", file=sys.stderr)
        sys.exit(1)
    server_sock.listen(128)

    print(f"  [proxy] Listening on {host}:{port}", file=sys.stderr)
    for domain, backend in backend_map.items():
        status = "ready" if cert_store.has_domain(domain) else "no cert"
        print(f"  [proxy]   {domain} -> {backend} [{status}]", file=sys.stderr)
    print(f"  [proxy] Certificates refresh every {refresh_hours}h", file=sys.stderr)

    try:
        while True:
            client_sock, addr = server_sock.accept()
            try:
                ssl_sock = base_ctx.wrap_socket(client_sock, server_side=True)
            except ssl.SSLError as e:
                print(
                    f"  [proxy] TLS handshake failed from {addr}: {e}", file=sys.stderr
                )
                client_sock.close()
                continue
            except OSError:
                client_sock.close()
                continue

            # Determine backend from SNI
            server_name = _last_sni[0]
            _last_sni[0] = ""
            backend = backend_map.get(server_name, "")
            if not backend:
                print(
                    f"  [proxy] No route for {server_name} from {addr}",
                    file=sys.stderr,
                )
                ssl_sock.close()
                continue

            threading.Thread(
                target=_forward, args=(ssl_sock, backend), daemon=True
            ).start()
    finally:
        refresher.stop()
        server_sock.close()
