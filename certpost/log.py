# ----------------------------------------------------------------------------------------
#   log.py
#   ------
#
#   In-memory log buffer for certpost. Captures log messages in a ring buffer
#   so they can be viewed in the admin panel. Also prints to stderr.
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

import collections
import datetime
import sys
import threading

# ----------------------------------------------------------------------------------------
#   Constants
# ----------------------------------------------------------------------------------------

_MAX_ENTRIES = 200

# ----------------------------------------------------------------------------------------
#   Module State
# ----------------------------------------------------------------------------------------

_lock = threading.Lock()
_entries: collections.deque[dict[str, str]] = collections.deque(maxlen=_MAX_ENTRIES)

# ----------------------------------------------------------------------------------------
#   Functions
# ----------------------------------------------------------------------------------------


# ----------------------------------------------------------------------------------------
def log(source: str, message: str) -> None:
    """Add a log entry and print to stderr."""
    timestamp = datetime.datetime.now(datetime.UTC).isoformat()
    entry = {"timestamp": timestamp, "source": source, "message": message}

    with _lock:
        _entries.append(entry)

    print(f"  [{source}] {message}", file=sys.stderr)


# ----------------------------------------------------------------------------------------
def get_entries() -> list[dict[str, str]]:
    """Return all log entries (newest last)."""
    with _lock:
        return list(_entries)
