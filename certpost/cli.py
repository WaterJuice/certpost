# ----------------------------------------------------------------------------------------
#   cli.py
#   ------
#
#   CLI argument parsing and server launch for certpost-server.
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
import secrets
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

_TOKEN_CHARS = "abcdefghijklmnopqrstuvwxyz0123456789"

# ----------------------------------------------------------------------------------------
#   Functions
# ----------------------------------------------------------------------------------------


# ----------------------------------------------------------------------------------------
def _create_parser() -> ArgsParser:
    """Build the argument parser with subcommands."""
    parser = ArgsParser(
        prog="certpost-server",
        description="Let's Encrypt certificate manager with DNS-01 via Cloudflare.",
        version=f"certpost-server: {VERSION_STR}\npython: {sys.version.split()[0]}",
    )

    parser.add_argument(
        "--license",
        action="store_true",
        dest="license",
        help="Show licence information and exit",
    )

    # 'run' command
    run_cmd = parser.add_command("run", help="Start the certpost server")
    run_cmd.add_argument(
        "--port",
        "-p",
        type=int,
        default=8443,
        metavar="PORT",
        help="Port to listen on (default: 8443)",
    )
    run_cmd.add_argument(
        "--host",
        "-H",
        type=str,
        default="0.0.0.0",
        metavar="HOST",
        help="Host to bind to (default: 0.0.0.0)",
    )
    run_cmd.add_argument(
        "--data-dir",
        "-d",
        type=str,
        required=True,
        metavar="DIR",
        help="Data directory containing config.json",
    )

    # 'setup' command
    setup_cmd = parser.add_command(
        "setup", help="Interactive setup wizard for config.json"
    )
    setup_cmd.add_argument(
        "--data-dir",
        "-d",
        type=str,
        required=True,
        metavar="DIR",
        help="Data directory to create config in",
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
def _prompt(label: str, default: str = "") -> str:
    """Prompt for input with an optional default."""
    if default:
        result = input(f"  {label} [{default}]: ").strip()
        return result if result else default
    result = input(f"  {label}: ").strip()
    return result


# ----------------------------------------------------------------------------------------
def _run_setup(data_dir_path: pathlib.Path) -> None:
    """Run interactive setup wizard to create or update config.json."""
    data_dir_path.mkdir(parents=True, exist_ok=True)
    (data_dir_path / "certs").mkdir(exist_ok=True)

    config_path = data_dir_path / "config.json"

    # Load existing config if present
    existing: dict[str, str | int] = {}
    if config_path.exists():
        existing = json.loads(config_path.read_text())
        print(f"\nUpdating existing config at {config_path}")
    else:
        print(f"\nCreating new config at {config_path}")

    print("Press Enter to skip any field — you can fill it in later.\n")

    print("Cloudflare DNS settings:")
    cf_token = _prompt(
        "Cloudflare API token",
        str(existing.get("cloudflare_api_token", "")),
    )
    cf_zone = _prompt(
        "Cloudflare Zone ID",
        str(existing.get("cloudflare_zone_id", "")),
    )

    print("\nDomain settings:")
    base_domain = _prompt(
        "Base domain (e.g. example.com)",
        str(existing.get("base_domain", "")),
    )

    print("\nServer settings:")
    port_str = _prompt("Port", str(existing.get("port", 8443)))
    port = int(port_str) if port_str.isdigit() else 8443

    # Generate admin key if not present
    admin_key = str(existing.get("admin_key", ""))
    if not admin_key:
        admin_key = "".join(secrets.choice(_TOKEN_CHARS) for _ in range(40))

    config: dict[str, object] = {
        "cloudflare_api_token": cf_token,
        "cloudflare_zone_id": cf_zone,
        "base_domain": base_domain,
        "admin_key": admin_key,
        "port": port,
    }

    # Preserve sessions if they exist
    if "sessions" in existing:
        config["sessions"] = existing["sessions"]

    tmp = config_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(config, indent=2) + "\n")
    tmp.rename(config_path)

    # Also create domains.json if missing
    domains_path = data_dir_path / "domains.json"
    if not domains_path.exists():
        tmp = domains_path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"domains": []}, indent=2) + "\n")
        tmp.rename(domains_path)

    print(f"\nConfig saved to {config_path}")
    print(f"Admin key: {admin_key}")
    print()


# ----------------------------------------------------------------------------------------
def _resolve_data_dir(args: Namespace) -> pathlib.Path:
    """Resolve the data directory from args."""
    return pathlib.Path(args.data_dir)


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

    command = args.command if hasattr(args, "command") else None

    if command == "setup":
        _run_setup(_resolve_data_dir(args))
        return 0

    if command == "run":
        data_dir_path = _resolve_data_dir(args)
        config_path = data_dir_path / "config.json"

        if not config_path.exists():
            print(
                f"No config found at {config_path}\n"
                f"Run 'certpost-server setup -d {args.data_dir}' to create one.",
                file=sys.stderr,
            )
            return 1

        print(f"certpost-server {VERSION_STR}", file=sys.stderr)
        print(f"Serving on http://{args.host}:{args.port}", file=sys.stderr)
        run_server(host=args.host, port=args.port, data_dir=args.data_dir)
        return 0

    # No command given — show help
    parser.parse(["--help"])
    return 0
