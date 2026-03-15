# ----------------------------------------------------------------------------------------
#   cloudflare.py
#   -------------
#
#   Cloudflare DNS API client for managing TXT records. Used for DNS-01 ACME challenges.
#   Uses a scoped API token (no IP whitelisting required).
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
import urllib.error
import urllib.request
from typing import Any

# ----------------------------------------------------------------------------------------
#   Types
# ----------------------------------------------------------------------------------------

type JsonDict = dict[str, Any]

# ----------------------------------------------------------------------------------------
#   Constants
# ----------------------------------------------------------------------------------------

_API_BASE = "https://api.cloudflare.com/client/v4"

# ----------------------------------------------------------------------------------------
#   Cloudflare client
# ----------------------------------------------------------------------------------------


# ----------------------------------------------------------------------------------------
class CloudflareClient:
    """Client for the Cloudflare DNS API."""

    # ------------------------------------------------------------------------------------
    #   Construction
    # ------------------------------------------------------------------------------------

    def __init__(self, api_token: str, zone_id: str) -> None:
        """Initialise the Cloudflare API client."""
        self._api_token = api_token
        self._zone_id = zone_id

    # ------------------------------------------------------------------------------------
    #   Private methods
    # ------------------------------------------------------------------------------------

    # ------------------------------------------------------------------------------------
    def _api_call(
        self,
        method: str,
        path: str,
        body: JsonDict | None = None,
    ) -> JsonDict:
        """Make an API call and return the parsed JSON response."""
        url = f"{_API_BASE}{path}"
        data = json.dumps(body).encode() if body else None

        req = urllib.request.Request(
            url,
            data=data,
            headers={
                "Authorization": f"Bearer {self._api_token}",
                "Content-Type": "application/json",
            },
            method=method,
        )

        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                result: JsonDict = json.loads(response.read())
        except urllib.error.HTTPError as e:
            error_body = e.read().decode()
            raise RuntimeError(f"Cloudflare API error ({e.code}): {error_body}") from e

        if not result.get("success", False):
            errors = result.get("errors", [])
            error_msgs = [str(e.get("message", "Unknown error")) for e in errors]
            raise RuntimeError(f"Cloudflare API error: {'; '.join(error_msgs)}")

        return result

    # ------------------------------------------------------------------------------------
    #   Public methods
    # ------------------------------------------------------------------------------------

    # ------------------------------------------------------------------------------------
    def set_txt_record(self, name: str, value: str) -> str:
        """Create a TXT record. Returns the record ID."""
        # First check if a record with this name already exists
        existing = self._find_txt_records(name)
        for record in existing:
            record_id = str(record.get("id", ""))
            if record_id:
                self._api_call(
                    "DELETE",
                    f"/zones/{self._zone_id}/dns_records/{record_id}",
                )

        # Create the new record
        result = self._api_call(
            "POST",
            f"/zones/{self._zone_id}/dns_records",
            {
                "type": "TXT",
                "name": name,
                "content": value,
                "ttl": 60,
            },
        )

        record_result: JsonDict = result.get("result", {})  # pyright: ignore[reportAssignmentType]
        return str(record_result.get("id", ""))

    # ------------------------------------------------------------------------------------
    def remove_txt_record(self, name: str) -> None:
        """Remove all TXT records matching the given name."""
        records = self._find_txt_records(name)
        for record in records:
            record_id = str(record.get("id", ""))
            if record_id:
                self._api_call(
                    "DELETE",
                    f"/zones/{self._zone_id}/dns_records/{record_id}",
                )

    # ------------------------------------------------------------------------------------
    def _find_txt_records(self, name: str) -> list[JsonDict]:
        """Find TXT records matching the given name."""
        result = self._api_call(
            "GET",
            f"/zones/{self._zone_id}/dns_records?type=TXT&name={name}",
        )
        records: list[JsonDict] = result.get("result", [])  # pyright: ignore[reportAssignmentType]
        return records
