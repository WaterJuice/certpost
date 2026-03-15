# ----------------------------------------------------------------------------------------
#   cli.py
#   ------
#
#   CLI argument parsing and server launch for certpost.
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
import sys
import traceback
from .argbuilder import ArgsParser
from .argbuilder import Namespace
from .server import run_server
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
        prog="certpost-server",
        description="Let's Encrypt certificate manager with DNS-01 via Namecheap.",
        version=f"certpost-server: {VERSION_STR}\npython: {sys.version.split()[0]}",
    )

    parser.add_argument(
        "--license",
        action="store_true",
        dest="license",
        help="Show licence information and exit",
    )
    parser.add_argument(
        "--port",
        "-p",
        type=int,
        default=8443,
        metavar="PORT",
        help="Port to listen on (default: 8443)",
    )
    parser.add_argument(
        "--host",
        "-H",
        type=str,
        default="0.0.0.0",
        metavar="HOST",
        help="Host to bind to (default: 0.0.0.0)",
    )
    parser.add_argument(
        "--data-dir",
        "-d",
        type=str,
        default="",
        metavar="DIR",
        help="Data directory (default: ~/.certpost)",
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
def main() -> int:
    """Entry point for the CLI."""
    try:
        return _main_inner()
    except KeyboardInterrupt:
        print("\nShutting down.", file=sys.stderr)
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

    data_dir = args.data_dir if args.data_dir else ""

    print(
        f"certpost-server {VERSION_STR}",
        file=sys.stderr,
    )
    print(
        f"Serving on http://{args.host}:{args.port}",
        file=sys.stderr,
    )

    run_server(host=args.host, port=args.port, data_dir=data_dir)
    return 0
