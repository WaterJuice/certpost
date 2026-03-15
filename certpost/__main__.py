# ----------------------------------------------------------------------------------------
#   __main__.py
#   -----------
#
#   Entry point for python -m certpost.
#
#   (c) 2026 WaterJuice — Released under the Unlicense; see LICENSE.
#
#   Version History
#   ---------------
#   Mar 2026 - Created
# ----------------------------------------------------------------------------------------

import sys

MIN_PYTHON = (3, 12)
if sys.version_info < MIN_PYTHON:
    print(
        f"Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+ is required. "
        f"You are using Python {sys.version_info.major}.{sys.version_info.minor}.",
        file=sys.stderr,
    )
    sys.exit(1)

from certpost.client_cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
