# ----------------------------------------------------------------------------------------
#   dns.py
#   ------
#
#   DNS provider protocol. Defines the interface that DNS backends must implement.
#   Currently only Cloudflare is implemented, but this makes it easy to add others.
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

from typing import Protocol

# ----------------------------------------------------------------------------------------
#   DNS Provider Protocol
# ----------------------------------------------------------------------------------------


# ----------------------------------------------------------------------------------------
class DnsProvider(Protocol):
    """Interface for DNS providers used by certpost."""

    # ------------------------------------------------------------------------------------
    def set_txt_record(self, name: str, value: str) -> str:
        """Create or replace a TXT record. Returns a record ID."""
        ...

    # ------------------------------------------------------------------------------------
    def remove_txt_record(self, name: str) -> None:
        """Remove all TXT records matching the given name."""
        ...

    # ------------------------------------------------------------------------------------
    def set_a_record(self, name: str, ip_address: str) -> str:
        """Create or replace an A record. Returns a record ID."""
        ...

    # ------------------------------------------------------------------------------------
    def remove_a_record(self, name: str) -> None:
        """Remove all A records matching the given name."""
        ...
