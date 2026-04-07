# ----------------------------------------------------------------------------------------
#   technitium.py
#   -------------
#
#   Technitium DNS Server API client for managing DNS records. Handles TXT records for
#   DNS-01 ACME challenges and A/CNAME records for subdomain pointing.
#
#   (c) 2026 WaterJuice — Released under the Unlicense; see LICENSE.
#
#   Version History
#   ---------------
#   Apr 2026 - Created
# ----------------------------------------------------------------------------------------

# ----------------------------------------------------------------------------------------
#   Imports
# ----------------------------------------------------------------------------------------

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

# ----------------------------------------------------------------------------------------
#   Types
# ----------------------------------------------------------------------------------------

type JsonDict = dict[str, Any]

# ----------------------------------------------------------------------------------------
#   Technitium client
# ----------------------------------------------------------------------------------------


# ----------------------------------------------------------------------------------------
class TechnitiumClient:
    """Client for the Technitium DNS Server API."""

    # ------------------------------------------------------------------------------------
    #   Construction
    # ------------------------------------------------------------------------------------

    def __init__(self, server_url: str, api_token: str, zone: str) -> None:
        """Initialise the Technitium DNS Server API client."""
        self._server_url = server_url.rstrip("/")
        self._api_token = api_token
        self._zone = zone

    # ------------------------------------------------------------------------------------
    #   Private methods
    # ------------------------------------------------------------------------------------

    # ------------------------------------------------------------------------------------
    def _api_call(self, endpoint: str, params: dict[str, str]) -> JsonDict:
        """Make an API call and return the parsed JSON response."""
        params["token"] = self._api_token
        query = urllib.parse.urlencode(params)
        url = f"{self._server_url}{endpoint}?{query}"

        req = urllib.request.Request(url, method="GET")

        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                result: JsonDict = json.loads(response.read())
        except urllib.error.HTTPError as e:
            error_body = e.read().decode()
            raise RuntimeError(f"Technitium API error ({e.code}): {error_body}") from e

        status = result.get("status", "")
        if status != "ok":
            error_msg = result.get("errorMessage", "Unknown error")
            raise RuntimeError(f"Technitium API error: {error_msg}")

        return result

    # ------------------------------------------------------------------------------------
    def _find_records(self, name: str, record_type: str) -> list[JsonDict]:
        """Find records of a given type matching the given name."""
        try:
            result = self._api_call(
                "/api/zones/records/get",
                {"domain": name, "zone": self._zone},
            )
        except RuntimeError:
            return []

        records: list[JsonDict] = result.get("response", {}).get("records", [])
        return [
            r for r in records if r.get("type") == record_type and r.get("name") == name
        ]

    # ------------------------------------------------------------------------------------
    #   Public methods
    # ------------------------------------------------------------------------------------

    # ------------------------------------------------------------------------------------
    def set_txt_record(self, name: str, value: str) -> str:
        """Create a TXT record. Returns the record name as ID."""
        # Remove any existing TXT records with this name
        self.remove_txt_record(name)

        self._api_call(
            "/api/zones/records/add",
            {
                "domain": name,
                "zone": self._zone,
                "type": "TXT",
                "ttl": "60",
                "text": value,
            },
        )
        return name

    # ------------------------------------------------------------------------------------
    def remove_txt_record(self, name: str) -> None:
        """Remove all TXT records matching the given name."""
        records = self._find_records(name, "TXT")
        for record in records:
            text = record.get("rData", {}).get("text", "")
            try:
                self._api_call(
                    "/api/zones/records/delete",
                    {
                        "domain": name,
                        "zone": self._zone,
                        "type": "TXT",
                        "text": text,
                    },
                )
            except RuntimeError:
                pass

    # ------------------------------------------------------------------------------------
    def set_a_record(self, name: str, ip_address: str) -> str:
        """Create or replace an A record. Returns the record name as ID."""
        self.remove_a_record(name)

        self._api_call(
            "/api/zones/records/add",
            {
                "domain": name,
                "zone": self._zone,
                "type": "A",
                "ttl": "300",
                "ipAddress": ip_address,
            },
        )
        return name

    # ------------------------------------------------------------------------------------
    def remove_a_record(self, name: str) -> None:
        """Remove all A records matching the given name."""
        records = self._find_records(name, "A")
        for record in records:
            ip_address = record.get("rData", {}).get("ipAddress", "")
            try:
                self._api_call(
                    "/api/zones/records/delete",
                    {
                        "domain": name,
                        "zone": self._zone,
                        "type": "A",
                        "ipAddress": ip_address,
                    },
                )
            except RuntimeError:
                pass

    # ------------------------------------------------------------------------------------
    def set_cname_record(self, name: str, target: str) -> str:
        """Create or replace a CNAME record. Returns the record name as ID."""
        self.remove_cname_record(name)

        self._api_call(
            "/api/zones/records/add",
            {
                "domain": name,
                "zone": self._zone,
                "type": "CNAME",
                "ttl": "300",
                "cname": target,
            },
        )
        return name

    # ------------------------------------------------------------------------------------
    def remove_cname_record(self, name: str) -> None:
        """Remove all CNAME records matching the given name."""
        records = self._find_records(name, "CNAME")
        for record in records:
            cname = record.get("rData", {}).get("cname", "")
            try:
                self._api_call(
                    "/api/zones/records/delete",
                    {
                        "domain": name,
                        "zone": self._zone,
                        "type": "CNAME",
                        "cname": cname,
                    },
                )
            except RuntimeError:
                pass
