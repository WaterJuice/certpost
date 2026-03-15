# ----------------------------------------------------------------------------------------
#   client_cli.py
#   -------------
#
#   CLI for the certpost client. Fetches certificates from a certpost server
#   and saves them locally as PEM files.
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
import urllib.error
import urllib.request
from .argbuilder import ArgsParser
from .argbuilder import Namespace
from .version import VERSION_STR

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

# ----------------------------------------------------------------------------------------
#   Functions
# ----------------------------------------------------------------------------------------


# ----------------------------------------------------------------------------------------
def _create_parser() -> ArgsParser:
    """Build the argument parser."""
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
    parser.add_argument(
        "--server",
        "-s",
        type=str,
        required=True,
        metavar="URL",
        help="certpost server URL (e.g. http://certpost.example.com:8443)",
    )
    parser.add_argument(
        "--token",
        "-t",
        type=str,
        required=True,
        metavar="TOKEN",
        help="Bearer token for authentication",
    )
    parser.add_argument(
        "--domain",
        "-d",
        type=str,
        required=True,
        metavar="FQDN",
        help="Fully qualified domain name to fetch certificate for",
    )
    parser.add_argument(
        "--output-dir",
        "-o",
        type=str,
        default=".",
        metavar="DIR",
        help="Directory to save certificate files (default: current directory)",
    )
    parser.add_argument(
        "--poll",
        type=int,
        default=0,
        metavar="SECONDS",
        help="Poll interval in seconds (0 = fetch once and exit)",
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
def _fetch_cert(server_url: str, token: str, domain: str) -> dict[str, str]:
    """Fetch certificate data from the server."""
    url = f"{server_url.rstrip('/')}/api/cert/{domain}"
    req = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {token}"},
        method="GET",
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            return json.loads(response.read())  # pyright: ignore[reportReturnType]
    except urllib.error.HTTPError as e:
        error_body = e.read().decode()
        raise RuntimeError(f"Server returned {e.code}: {error_body}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"Could not connect to server: {e.reason}") from e


# ----------------------------------------------------------------------------------------
def _save_cert(
    output_dir: pathlib.Path, domain: str, cert_data: dict[str, str]
) -> None:
    """Save certificate files to disk."""
    output_dir.mkdir(parents=True, exist_ok=True)

    cert_path = output_dir / f"{domain}.crt"
    key_path = output_dir / f"{domain}.key"

    cert_pem = cert_data.get("cert_pem", "")
    chain_pem = cert_data.get("chain_pem", "")
    key_pem = cert_data.get("key_pem", "")

    cert_path.write_text(cert_pem + chain_pem)
    key_path.write_text(key_pem)
    key_path.chmod(0o600)

    print(f"Wrote public cert to {cert_path}")
    print(f"Wrote private key to {key_path}")


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
    # Handle --license before parsing.
    if "--license" in sys.argv or "--licence" in sys.argv:
        _show_licence()
        return 0

    parser = _create_parser()
    args: Namespace = parser.parse()

    print(f"certpost {VERSION_STR}", file=sys.stderr)

    output_dir = pathlib.Path(args.output_dir)
    poll_interval: int = args.poll

    while True:
        print(
            f"Fetching certificate for {args.domain} from {args.server}...",
            file=sys.stderr,
        )
        try:
            cert_data = _fetch_cert(args.server, args.token, args.domain)
            _save_cert(output_dir, args.domain, cert_data)
            print("Done.", file=sys.stderr)
        except RuntimeError as e:
            print(f"Error: {e}", file=sys.stderr)
            if poll_interval <= 0:
                return 1

        if poll_interval <= 0:
            break

        print(f"Sleeping {poll_interval}s until next check...", file=sys.stderr)
        time.sleep(poll_interval)

    return 0
