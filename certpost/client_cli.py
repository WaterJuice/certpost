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

    # 'fetch' command — one-shot or recurring cert fetch
    fetch_cmd = parser.add_command(
        "fetch", help="Fetch certificates and save as PEM files"
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
        help="Bearer token for authentication",
    )
    fetch_cmd.add_argument(
        "--domain",
        "-d",
        type=str,
        metavar="FQDN",
        help="Domain to fetch certificate for",
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
        help="Refresh interval in hours (0 = fetch once, default: 0)",
    )
    fetch_cmd.add_argument(
        "--config",
        "-c",
        type=str,
        default="",
        metavar="FILE",
        help="Config file (JSON) instead of CLI args",
    )

    # 'proxy' command — TLS termination proxy
    proxy_cmd = parser.add_command(
        "proxy", help="TLS termination proxy with SNI routing"
    )
    proxy_cmd.add_argument(
        "--config",
        "-c",
        type=str,
        default="",
        metavar="FILE",
        help="Config file (JSON) — required for proxy mode",
    )
    proxy_cmd.add_argument(
        "--listen",
        type=str,
        default="0.0.0.0:443",
        metavar="ADDR",
        help="Listen address (default: 0.0.0.0:443)",
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

    if command == "fetch":
        return _run_fetch(args)

    if command == "proxy":
        return _run_proxy(args)

    # No command — show help
    parser.parse(["--help"])
    return 0
