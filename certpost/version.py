# ----------------------------------------------------------------------------------------
#   version.py
#   ----------
#
#   Version string handling — imports from generated _version.py at build time,
#   falls back to "dev" when not built.
#
#   (c) 2026 WaterJuice — Released under the Unlicense; see LICENSE.
#
#   Version History
#   ---------------
#   Mar 2026 - Created
# ----------------------------------------------------------------------------------------

# pyright: reportMissingImports=false
# pyright: reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false

# ----------------------------------------------------------------------------------------
#   Version
# ----------------------------------------------------------------------------------------


def _get_version() -> str:
    try:
        from ._version import __version__ as _v  # noqa: I001

        return str(_v)
    except ImportError:
        return "dev"


VERSION_STR: str = _get_version()
