# ----------------------------------------------------------------------------------------
#   namecheap.py
#   ------------
#
#   Namecheap DNS API client for managing TXT records. Used for DNS-01 ACME challenges.
#   Always fetches existing records before writing since setHosts replaces all records.
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

import threading
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from typing import Any

# ----------------------------------------------------------------------------------------
#   Types
# ----------------------------------------------------------------------------------------

type JsonDict = dict[str, Any]

# ----------------------------------------------------------------------------------------
#   Constants
# ----------------------------------------------------------------------------------------

_API_BASE = "https://api.namecheap.com/xml.response"

# ----------------------------------------------------------------------------------------
#   Namecheap client
# ----------------------------------------------------------------------------------------


# ----------------------------------------------------------------------------------------
class NamecheapClient:
    """Client for the Namecheap DNS API."""

    # ------------------------------------------------------------------------------------
    #   Construction
    # ------------------------------------------------------------------------------------

    def __init__(
        self, api_user: str, api_key: str, username: str, client_ip: str
    ) -> None:
        """Initialise the Namecheap API client."""
        self._api_user = api_user
        self._api_key = api_key
        self._username = username
        self._client_ip = client_ip
        self._lock = threading.Lock()

    # ------------------------------------------------------------------------------------
    #   Private methods
    # ------------------------------------------------------------------------------------

    # ------------------------------------------------------------------------------------
    def _api_params(self, command: str) -> dict[str, str]:
        """Return base API parameters."""
        return {
            "ApiUser": self._api_user,
            "ApiKey": self._api_key,
            "UserName": self._username,
            "ClientIp": self._client_ip,
            "Command": command,
        }

    # ------------------------------------------------------------------------------------
    def _api_call(self, params: dict[str, str]) -> ET.Element:
        """Make an API call and return the parsed XML root element."""
        url = _API_BASE + "?" + urllib.parse.urlencode(params)
        with urllib.request.urlopen(url, timeout=30) as response:
            body = response.read()
        root = ET.fromstring(body)

        status = root.get("Status", "")
        if status != "OK":
            errors = root.find(".//{http://api.namecheap.com/xml.response}Errors")
            if errors is not None:
                error_msgs = [e.text or "Unknown error" for e in errors]
                raise RuntimeError(f"Namecheap API error: {'; '.join(error_msgs)}")
            raise RuntimeError(f"Namecheap API returned status: {status}")

        return root

    # ------------------------------------------------------------------------------------
    @staticmethod
    def _split_domain(domain: str) -> tuple[str, str]:
        """Split a full domain into SLD and TLD (e.g. 'example.com' -> ('example', 'com'))."""
        parts = domain.rsplit(".", 1)
        if len(parts) != 2:
            raise ValueError(f"Invalid domain: {domain}")
        return parts[0], parts[1]

    # ------------------------------------------------------------------------------------
    #   Public methods
    # ------------------------------------------------------------------------------------

    # ------------------------------------------------------------------------------------
    def get_hosts(self, domain: str) -> list[JsonDict]:
        """Fetch all DNS host records for a domain."""
        sld, tld = self._split_domain(domain)
        params = self._api_params("namecheap.domains.dns.getHosts")
        params["SLD"] = sld
        params["TLD"] = tld

        with self._lock:
            root = self._api_call(params)

        ns = "{http://api.namecheap.com/xml.response}"
        hosts: list[JsonDict] = []
        for host in root.iter(f"{ns}host"):
            hosts.append(
                {
                    "HostName": host.get("Name", ""),
                    "RecordType": host.get("Type", ""),
                    "Address": host.get("Address", ""),
                    "MXPref": host.get("MXPref", "10"),
                    "TTL": host.get("TTL", "1800"),
                }
            )
        return hosts

    # ------------------------------------------------------------------------------------
    def set_hosts(self, domain: str, hosts: list[JsonDict]) -> None:
        """Set all DNS host records for a domain (replaces existing records)."""
        sld, tld = self._split_domain(domain)
        params = self._api_params("namecheap.domains.dns.setHosts")
        params["SLD"] = sld
        params["TLD"] = tld

        for i, host in enumerate(hosts, 1):
            params[f"HostName{i}"] = host["HostName"]
            params[f"RecordType{i}"] = host["RecordType"]
            params[f"Address{i}"] = host["Address"]
            params[f"MXPref{i}"] = host.get("MXPref", "10")
            params[f"TTL{i}"] = host.get("TTL", "1800")

        with self._lock:
            self._api_call(params)

    # ------------------------------------------------------------------------------------
    def set_txt_record(self, domain: str, hostname: str, value: str) -> None:
        """Add or update a TXT record, preserving all other records."""
        with self._lock:
            # Must hold lock for entire read-modify-write cycle
            sld, tld = self._split_domain(domain)
            params = self._api_params("namecheap.domains.dns.getHosts")
            params["SLD"] = sld
            params["TLD"] = tld
            root = self._api_call(params)

            ns = "{http://api.namecheap.com/xml.response}"
            hosts: list[JsonDict] = []
            for host in root.iter(f"{ns}host"):
                h: JsonDict = {
                    "HostName": host.get("Name", ""),
                    "RecordType": host.get("Type", ""),
                    "Address": host.get("Address", ""),
                    "MXPref": host.get("MXPref", "10"),
                    "TTL": host.get("TTL", "1800"),
                }
                # Skip existing record with same hostname and type
                if h["HostName"] == hostname and h["RecordType"] == "TXT":
                    continue
                hosts.append(h)

            # Add the new TXT record
            hosts.append(
                {
                    "HostName": hostname,
                    "RecordType": "TXT",
                    "Address": value,
                    "MXPref": "10",
                    "TTL": "60",
                }
            )

            # Write all records back
            set_params = self._api_params("namecheap.domains.dns.setHosts")
            set_params["SLD"] = sld
            set_params["TLD"] = tld
            for i, host in enumerate(hosts, 1):
                set_params[f"HostName{i}"] = host["HostName"]
                set_params[f"RecordType{i}"] = host["RecordType"]
                set_params[f"Address{i}"] = host["Address"]
                set_params[f"MXPref{i}"] = host.get("MXPref", "10")
                set_params[f"TTL{i}"] = host.get("TTL", "1800")

            self._api_call(set_params)

    # ------------------------------------------------------------------------------------
    def remove_txt_record(self, domain: str, hostname: str) -> None:
        """Remove a TXT record by hostname, preserving all other records."""
        with self._lock:
            sld, tld = self._split_domain(domain)
            params = self._api_params("namecheap.domains.dns.getHosts")
            params["SLD"] = sld
            params["TLD"] = tld
            root = self._api_call(params)

            ns = "{http://api.namecheap.com/xml.response}"
            hosts: list[JsonDict] = []
            for host in root.iter(f"{ns}host"):
                h: JsonDict = {
                    "HostName": host.get("Name", ""),
                    "RecordType": host.get("Type", ""),
                    "Address": host.get("Address", ""),
                    "MXPref": host.get("MXPref", "10"),
                    "TTL": host.get("TTL", "1800"),
                }
                if h["HostName"] == hostname and h["RecordType"] == "TXT":
                    continue
                hosts.append(h)

            set_params = self._api_params("namecheap.domains.dns.setHosts")
            set_params["SLD"] = sld
            set_params["TLD"] = tld
            for i, host in enumerate(hosts, 1):
                set_params[f"HostName{i}"] = host["HostName"]
                set_params[f"RecordType{i}"] = host["RecordType"]
                set_params[f"Address{i}"] = host["Address"]
                set_params[f"MXPref{i}"] = host.get("MXPref", "10")
                set_params[f"TTL{i}"] = host.get("TTL", "1800")

            self._api_call(set_params)
