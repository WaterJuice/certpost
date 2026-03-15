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

# ----------------------------------------------------------------------------------------
#   Version
# ----------------------------------------------------------------------------------------


def _get_version() -> str:
    try:
        # fmt: off
        from ._version import __version__ as _v  # pyright: ignore[reportMissingImports,reportUnknownVariableType]  # noqa: I001
        # fmt: on

        return str(_v)  # pyright: ignore[reportUnknownArgumentType]
    except ImportError:
        return "dev"


VERSION_STR: str = _get_version()
