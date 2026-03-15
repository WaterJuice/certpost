# ----------------------------------------------------------------------------------------
#   renewal.py
#   ----------
#
#   Background certificate renewal thread. Checks daily and renews certificates
#   that are within 30 days of expiry.
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

import datetime
import sys
import threading
import traceback
from .acme import AcmeClient
from .storage import Storage

# ----------------------------------------------------------------------------------------
#   Constants
# ----------------------------------------------------------------------------------------

_CHECK_INTERVAL = 86400  # 24 hours
_RENEWAL_WINDOW = 30 * 86400  # 30 days before expiry

# ----------------------------------------------------------------------------------------
#   Renewal Thread
# ----------------------------------------------------------------------------------------


# ----------------------------------------------------------------------------------------
class RenewalThread:
    """Background thread that checks and renews certificates."""

    # ------------------------------------------------------------------------------------
    #   Construction
    # ------------------------------------------------------------------------------------

    def __init__(self, storage: Storage, acme: AcmeClient) -> None:
        """Initialise the renewal thread."""
        self._storage = storage
        self._acme = acme
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    # ------------------------------------------------------------------------------------
    #   Public methods
    # ------------------------------------------------------------------------------------

    # ------------------------------------------------------------------------------------
    def start(self) -> None:
        """Start the renewal thread."""
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="cert-renewal"
        )
        self._thread.start()

    # ------------------------------------------------------------------------------------
    def stop(self) -> None:
        """Signal the renewal thread to stop."""
        self._stop_event.set()

    # ------------------------------------------------------------------------------------
    #   Private methods
    # ------------------------------------------------------------------------------------

    # ------------------------------------------------------------------------------------
    def _run(self) -> None:
        """Main loop — check for renewals, then sleep until next check."""
        # Initial delay to let the server start up
        if self._stop_event.wait(10):
            return

        while not self._stop_event.is_set():
            try:
                self._check_renewals()
            except Exception:
                print(
                    f"  [renewal] Error during renewal check:\n{traceback.format_exc()}",
                    file=sys.stderr,
                )

            # Sleep until next check (or until stopped)
            if self._stop_event.wait(_CHECK_INTERVAL):
                return

    # ------------------------------------------------------------------------------------
    def _check_renewals(self) -> None:
        """Check all domains and renew certificates that are near expiry."""
        domains = self._storage.get_domains()
        now = datetime.datetime.now(datetime.UTC)

        for domain in domains:
            subdomain = domain.get("subdomain", "")
            status = domain.get("status", "")
            expires_at_str = domain.get("cert_expires_at")

            if not subdomain:
                continue

            # Issue certs for pending domains
            if status == "pending":
                self._issue_cert(subdomain)
                continue

            # Renew certs within the renewal window
            if status == "issued" and expires_at_str is not None:
                expires_at = datetime.datetime.fromisoformat(str(expires_at_str))
                time_remaining = (expires_at - now).total_seconds()
                if time_remaining < _RENEWAL_WINDOW:
                    days_left = time_remaining / 86400
                    print(
                        f"  [renewal] Certificate for {subdomain} expires in {days_left:.0f} days, renewing...",
                        file=sys.stderr,
                    )
                    self._issue_cert(subdomain)

    # ------------------------------------------------------------------------------------
    def _issue_cert(self, subdomain: str) -> None:
        """Issue or renew a certificate for a subdomain."""
        try:
            self._storage.update_domain(subdomain, {"status": "issuing"})
            self._acme.issue_certificate(subdomain)
        except Exception as e:
            error_msg = f"{type(e).__name__}: {e}"
            print(
                f"  [renewal] Failed to issue cert for {subdomain}: {error_msg}",
                file=sys.stderr,
            )
            self._storage.update_domain(
                subdomain,
                {
                    "status": "error",
                    "last_error": error_msg,
                },
            )
