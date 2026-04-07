# ----------------------------------------------------------------------------------------
#   dns.py
#   ------
#
#   DNS provider protocol and factory. Defines the interface that DNS backends must
#   implement and provides a factory function to create providers from configuration.
#
#   (c) 2026 WaterJuice — Released under the Unlicense; see LICENSE.
#
#   Version History
#   ---------------
#   Mar 2026 - Created
#   Apr 2026 - Added factory function and Technitium support
# ----------------------------------------------------------------------------------------

# ----------------------------------------------------------------------------------------
#   Imports
# ----------------------------------------------------------------------------------------

from typing import Any
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

    # ------------------------------------------------------------------------------------
    def set_cname_record(self, name: str, target: str) -> str:
        """Create or replace a CNAME record. Returns a record ID."""
        ...

    # ------------------------------------------------------------------------------------
    def remove_cname_record(self, name: str) -> None:
        """Remove all CNAME records matching the given name."""
        ...


# ----------------------------------------------------------------------------------------
#   Types
# ----------------------------------------------------------------------------------------

type JsonDict = dict[str, Any]

# ----------------------------------------------------------------------------------------
#   Supported providers
# ----------------------------------------------------------------------------------------

_PROVIDER_NAMES = ("cloudflare", "technitium")

# ----------------------------------------------------------------------------------------
#   Factory
# ----------------------------------------------------------------------------------------


# ----------------------------------------------------------------------------------------
def create_dns_provider(config: JsonDict) -> DnsProvider:
    """Create a DNS provider from a configuration dict.

    The config dict must have a ``provider`` key set to one of the supported
    provider names.  Remaining keys are passed to the provider constructor.

    Cloudflare config::

        {"provider": "cloudflare", "api_token": "...", "zone_id": "..."}

    Technitium config::

        {"provider": "technitium", "server_url": "...", "api_token": "...", "zone": "..."}
    """
    provider_name = str(config.get("provider", ""))
    if not provider_name:
        raise ValueError("DNS provider config missing 'provider' key")

    if provider_name == "cloudflare":
        from .cloudflare import CloudflareClient

        api_token = str(config.get("api_token", ""))
        zone_id = str(config.get("zone_id", ""))
        if not api_token or not zone_id:
            raise ValueError("Cloudflare provider requires 'api_token' and 'zone_id'")
        return CloudflareClient(api_token=api_token, zone_id=zone_id)

    if provider_name == "technitium":
        from .technitium import TechnitiumClient

        server_url = str(config.get("server_url", ""))
        api_token = str(config.get("api_token", ""))
        zone = str(config.get("zone", ""))
        if not server_url or not api_token or not zone:
            raise ValueError(
                "Technitium provider requires 'server_url', 'api_token', and 'zone'"
            )
        return TechnitiumClient(server_url=server_url, api_token=api_token, zone=zone)

    raise ValueError(
        f"Unknown DNS provider: {provider_name!r} "
        f"(supported: {', '.join(_PROVIDER_NAMES)})"
    )
