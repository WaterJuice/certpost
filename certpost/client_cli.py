# ----------------------------------------------------------------------------------------
#   client_cli.py
#   -------------
#
#   CLI for the certpost client. Subcommands:
#     fetch  - Fetch certificates from a certpost server and save as PEM files
#     proxy  - TLS termination proxy with SNI routing and auto-refresh
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
import time
import traceback
from typing import Any
from .argbuilder import ArgsParser
from .argbuilder import Namespace
from .client_fetch import fetch_cert
from .client_fetch import save_cert
from .proxy import run_proxy
from .version import VERSION_STR

# ----------------------------------------------------------------------------------------
#   Types
# ----------------------------------------------------------------------------------------

type JsonDict = dict[str, Any]

# ----------------------------------------------------------------------------------------
#   Constants
# ----------------------------------------------------------------------------------------

_LICENCE_FILE = pathlib.Path(__file__).parent.parent / "LICENSE"

_LICENCE_TEXT = """\
This is free and unencumbered software released into the public domain.

Anyone is free to copy, modify, publish, use, compile, sell, or
distribute this software, either in source code form or as a compiled
binary, for any purpose, commercial or non-commercial, and by any
means.

For more information, please refer to <https://unlicense.org/>"""

_DEFAULT_REFRESH_HOURS = 24

# ----------------------------------------------------------------------------------------
#   Functions
# ----------------------------------------------------------------------------------------


# ----------------------------------------------------------------------------------------
def _create_parser() -> ArgsParser:
    """Build the argument parser with subcommands."""
    parser = ArgsParser(
        prog="certpost",
        description="Fetch certificates from a certpost server.",
        version=f"certpost: {VERSION_STR}\npython: {sys.version.split()[0]}",
    )

    parser.add_argument(
        "--license",
        action="store_true",
        dest="license",
        help="Show licence information and exit",
    )

    # 'fetch' command
    fetch_cmd = parser.add_command(
        "fetch",
        help="Fetch certificates and save as .crt/.key files",
        description="Download certificates from a certpost server and save them as <domain>.crt and <domain>.key files. Use --refresh to keep fetching on a schedule (e.g. every 24 hours) so renewed certs are picked up automatically. Options can be provided via CLI flags or a JSON config file (--config). Use 'certpost init' to create a config.",
    )
    fetch_cmd.add_argument(
        "--server",
        "-s",
        type=str,
        metavar="URL",
        help="certpost server URL (e.g. http://certpost.example.com:8443)",
    )
    fetch_cmd.add_argument(
        "--token",
        "-t",
        type=str,
        metavar="TOKEN",
        help="API token for the domain (from the certpost admin panel)",
    )
    fetch_cmd.add_argument(
        "--domain",
        "-d",
        type=str,
        metavar="FQDN",
        help="Domain to fetch certificate for (e.g. app.example.com)",
    )
    fetch_cmd.add_argument(
        "--output-dir",
        "-o",
        type=str,
        default=".",
        metavar="DIR",
        help="Directory to save certificate files (default: current directory)",
    )
    fetch_cmd.add_argument(
        "--refresh",
        type=int,
        default=0,
        metavar="HOURS",
        help="Re-fetch interval in hours; 0 = fetch once and exit (default: 0)",
    )
    fetch_cmd.add_argument(
        "--config",
        "-c",
        type=str,
        default="",
        metavar="FILE",
        help="JSON config file (alternative to CLI flags; see above for format)",
    )

    # 'init' command
    init_cmd = parser.add_command(
        "init",
        help="Generate a config file interactively",
        description=(
            "Interactive wizard to create a certpost JSON config file.\n"
            "Generates either a fetch config or a proxy config.\n"
            "Run 'certpost init' and follow the prompts."
        ),
    )
    init_cmd.add_argument(
        "--output",
        "-o",
        type=str,
        default="certpost.json",
        metavar="FILE",
        help="Output config file path (default: certpost.json)",
    )

    # 'proxy' command
    proxy_cmd = parser.add_command(
        "proxy",
        help="TLS termination proxy with auto-refreshing certs",
        description="Run a TLS termination proxy that fetches certificates from a certpost server, terminates TLS using SNI to select the right certificate, and forwards plaintext traffic to backend servers. Certificates are refreshed automatically (default: every 24 hours). Requires a JSON config file. Use 'certpost init' to create one.",
    )
    proxy_cmd.add_argument(
        "--config",
        "-c",
        type=str,
        default="",
        metavar="FILE",
        help="JSON config file (required; use 'certpost init' to create one)",
    )
    proxy_cmd.add_argument(
        "--listen",
        type=str,
        default="0.0.0.0:443",
        metavar="ADDR",
        help="Listen address, overrides config (default: 0.0.0.0:443)",
    )

    return parser


# ----------------------------------------------------------------------------------------
def _show_licence() -> None:
    """Print licence information and exit."""
    if _LICENCE_FILE.exists():
        print(_LICENCE_FILE.read_text())
    else:
        print(_LICENCE_TEXT)


# ----------------------------------------------------------------------------------------
def _load_config(config_path: str) -> JsonDict:
    """Load a JSON config file."""
    path = pathlib.Path(config_path)
    if not path.exists():
        raise RuntimeError(f"Config file not found: {config_path}")
    return json.loads(path.read_text())  # pyright: ignore[reportReturnType]


# ----------------------------------------------------------------------------------------
def _prompt(label: str, default: str = "") -> str:
    """Prompt for input with an optional default."""
    if default:
        result = input(f"  {label} [{default}]: ").strip()
        return result if result else default
    result = input(f"  {label}: ").strip()
    return result


# ----------------------------------------------------------------------------------------
def _run_init(args: Namespace) -> int:
    """Generate a config file interactively."""
    output_path = pathlib.Path(args.output)

    if output_path.exists():
        overwrite = (
            input(f"{output_path} already exists. Overwrite? [y/N]: ").strip().lower()
        )
        if overwrite != "y":
            print("Aborted.", file=sys.stderr)
            return 1

    print("\ncertpost config generator")
    print("Press Enter to skip any field — you can fill it in later.\n")

    print("What do you need?")
    print("  1. fetch  — download cert files to disk (one-shot or scheduled)")
    print("  2. proxy  — TLS termination proxy (auto-fetches and refreshes certs)")
    mode = _prompt("Choose [1/2]", "2")

    server = _prompt("certpost server URL (e.g. http://certpost.example.com:8443)")

    if mode == "2":
        config = _build_proxy_config(server)
    else:
        config = _build_fetch_config(server)

    # Validate against server if we have one
    if server:
        print("\nValidating configuration against server...")
        _validate_config(server, config, mode)

    tmp = output_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(config, indent=2) + "\n")
    tmp.rename(output_path)

    print(f"\nConfig saved to {output_path}")
    if mode == "2":
        print(f"Run with: certpost proxy -c {output_path}")
    else:
        print(f"Run with: certpost fetch -c {output_path}")
    print()
    return 0


# ----------------------------------------------------------------------------------------
def _validate_config(server: str, config: JsonDict, mode: str) -> None:
    """Validate config against the server, printing results."""
    # Check server is reachable
    try:
        import urllib.request

        url = f"{server.rstrip('/')}/api/version"
        with urllib.request.urlopen(url, timeout=10) as response:
            data = json.loads(response.read())
            print(
                f"  Server: {data.get('product', '?')} {data.get('server_version', '?')}"
            )
    except Exception as e:
        print(f"  WARNING: Could not reach server: {e}")
        return

    if mode == "2":
        # Proxy — validate each route's token
        routes: dict[str, JsonDict] = config.get("routes", {})  # pyright: ignore[reportAssignmentType]
        for domain, route in routes.items():
            token = str(route.get("token", ""))
            if _validate_token(server, token, domain):
                print(f"  {domain}: OK")
            else:
                print(
                    f"  {domain}: WARNING — token could not fetch cert (domain may not be issued yet)"
                )
    else:
        # Fetch — validate single token
        domain = str(config.get("domain", ""))
        token = str(config.get("token", ""))
        if domain and token:
            if _validate_token(server, token, domain):
                print(f"  {domain}: OK")
            else:
                print(
                    f"  {domain}: WARNING — token could not fetch cert (domain may not be issued yet)"
                )


# ----------------------------------------------------------------------------------------
def _build_fetch_config(server: str) -> JsonDict:
    """Build a fetch config interactively."""
    print("\nFetch settings:")
    domain = _prompt("Domain (e.g. app.example.com)")
    token = _prompt("API token for this domain")
    output_dir = _prompt("Output directory for cert files", ".")
    refresh_str = _prompt("Refresh interval in hours (0 = once)", "0")
    refresh_hours = int(refresh_str) if refresh_str.isdigit() else 0

    return {
        "server": server,
        "domain": domain,
        "token": token,
        "output_dir": output_dir,
        "refresh_hours": refresh_hours,
    }


# ----------------------------------------------------------------------------------------
def _resolve_domain_from_token(server_url: str, token: str) -> str:
    """Ask the server which domain a token belongs to. Returns empty string on failure."""
    if not server_url:
        return ""
    try:
        import urllib.request

        url = f"{server_url.rstrip('/')}/api/token-info"
        req = urllib.request.Request(
            url,
            headers={"Authorization": f"Bearer {token}"},
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read())
            return str(data.get("domain", ""))
    except Exception:
        return ""


# ----------------------------------------------------------------------------------------
def _validate_token(server_url: str, token: str, domain: str) -> bool:
    """Verify a token can fetch a cert for a domain. Returns True if valid."""
    if not server_url or not token or not domain:
        return False
    try:
        fetch_cert(server_url, token, domain)
        return True
    except Exception:
        return False


# ----------------------------------------------------------------------------------------
def _build_proxy_config(server: str) -> JsonDict:
    """Build a proxy config interactively."""
    print("\nProxy settings:")
    listen_input = _prompt("Listen port or address", "443")
    listen = f"0.0.0.0:{listen_input}" if listen_input.isdigit() else listen_input
    refresh_str = _prompt("Certificate refresh interval in hours", "24")
    refresh_hours = int(refresh_str) if refresh_str.isdigit() else 24

    routes: dict[str, JsonDict] = {}
    print("\nAdd routes. Enter empty token when done.\n")
    while True:
        token = _prompt("API token (from certpost admin panel)")
        if not token:
            break

        # Try to resolve domain from token
        domain = _resolve_domain_from_token(server, token)
        if domain:
            print(f"  Domain: {domain}")
        else:
            domain = _prompt("  Could not look up domain. Enter it manually")
            if not domain:
                continue

        while True:
            backend = _prompt(f"  Backend address for {domain} (e.g. 127.0.0.1:8080)")
            if backend:
                break
            print("  Backend address is required.")
        routes[domain] = {"token": token, "backend": backend}
        print()

    return {
        "server": server,
        "listen": listen,
        "refresh_hours": refresh_hours,
        "routes": routes,
    }


# ----------------------------------------------------------------------------------------
def _run_fetch(args: Namespace) -> int:
    """Run the fetch command."""
    # Load from config file or CLI args
    if args.config:
        config = _load_config(args.config)
        server = str(config.get("server", ""))
        token = str(config.get("token", ""))
        domain = str(config.get("domain", ""))
        output_dir = pathlib.Path(str(config.get("output_dir", ".")))
        refresh_hours = int(config.get("refresh_hours", 0))
    else:
        server = args.server or ""
        token = args.token or ""
        domain = args.domain or ""
        output_dir = pathlib.Path(args.output_dir)
        refresh_hours = args.refresh

    if not server or not token or not domain:
        print(
            "Error: --server, --token, and --domain are required (or use --config)",
            file=sys.stderr,
        )
        return 1

    refresh_seconds = refresh_hours * 3600

    while True:
        print(f"Fetching certificate for {domain}...", file=sys.stderr)
        try:
            cert_data = fetch_cert(server, token, domain)
            save_cert(output_dir, domain, cert_data)
        except RuntimeError as e:
            print(f"Error: {e}", file=sys.stderr)
            if refresh_seconds <= 0:
                return 1

        if refresh_seconds <= 0:
            break

        print(f"Next refresh in {refresh_hours}h", file=sys.stderr)
        time.sleep(refresh_seconds)

    return 0


# ----------------------------------------------------------------------------------------
def _run_proxy(args: Namespace) -> int:
    """Run the proxy command."""
    config_path = args.config
    if not config_path:
        print("Error: --config is required for proxy mode", file=sys.stderr)
        print("", file=sys.stderr)
        print("Example config file:", file=sys.stderr)
        print(
            json.dumps(
                {
                    "server": "http://certpost.example.com:8443",
                    "listen": "0.0.0.0:443",
                    "refresh_hours": 24,
                    "routes": {
                        "app.example.com": {
                            "token": "your-api-token",
                            "backend": "127.0.0.1:8080",
                        },
                        "api.example.com": {
                            "token": "another-api-token",
                            "backend": "127.0.0.1:9090",
                        },
                    },
                },
                indent=2,
            ),
            file=sys.stderr,
        )
        return 1

    config = _load_config(config_path)
    listen = (
        args.listen
        if args.listen != "0.0.0.0:443"
        else str(config.get("listen", "0.0.0.0:443"))
    )

    run_proxy(config, listen)
    return 0


# ----------------------------------------------------------------------------------------
def main() -> int:
    """Entry point for the CLI."""
    try:
        return _main_inner()
    except KeyboardInterrupt:
        print("\nStopped.", file=sys.stderr)
        return 0
    except SystemExit:
        raise
    except BaseException as e:
        t = "-------------------------------------------------------------------\n"
        t += "UNHANDLED EXCEPTION OCCURRED!!\n"
        t += "\n"
        t += traceback.format_exc()
        t += "\n"
        t += f"EXCEPTION: {type(e)} {e}\n"
        t += "-------------------------------------------------------------------\n"
        print(t, file=sys.stderr)
        return 1


# ----------------------------------------------------------------------------------------
def _main_inner() -> int:
    """Inner main function that does the actual work."""
    if "--license" in sys.argv or "--licence" in sys.argv:
        _show_licence()
        return 0

    parser = _create_parser()
    args: Namespace = parser.parse()

    command = args.command if hasattr(args, "command") else None

    if command == "init":
        return _run_init(args)

    if command == "fetch":
        return _run_fetch(args)

    if command == "proxy":
        return _run_proxy(args)

    # No command — show help
    parser.parse(["--help"])
    return 0
