# ----------------------------------------------------------------------------------------
#   storage.py
#   ----------
#
#   JSON file storage for certpost. Manages configuration, certificates, and
#   per-domain API tokens in ~/.certpost/. All file writes are protected by a
#   threading lock.
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
import json
import pathlib
import secrets
import threading
from typing import Any

# ----------------------------------------------------------------------------------------
#   Constants
# ----------------------------------------------------------------------------------------

_DEFAULT_DATA_DIR = pathlib.Path.home() / ".certpost"

# ----------------------------------------------------------------------------------------
#   Types
# ----------------------------------------------------------------------------------------

type JsonDict = dict[str, Any]

# ----------------------------------------------------------------------------------------
#   Storage class
# ----------------------------------------------------------------------------------------


# ----------------------------------------------------------------------------------------
class Storage:
    """Manages JSON file storage for certpost data."""

    # ------------------------------------------------------------------------------------
    #   Construction
    # ------------------------------------------------------------------------------------

    def __init__(self, data_dir: str = "") -> None:
        """Initialise storage with the given data directory."""
        self._data_dir = pathlib.Path(data_dir) if data_dir else _DEFAULT_DATA_DIR
        self._lock = threading.Lock()
        self._initialise_data_dir()

    # ------------------------------------------------------------------------------------
    #   Properties
    # ------------------------------------------------------------------------------------

    @property
    def data_dir(self) -> pathlib.Path:
        """Return the data directory path."""
        return self._data_dir

    # ------------------------------------------------------------------------------------
    #   Private methods
    # ------------------------------------------------------------------------------------

    # ------------------------------------------------------------------------------------
    def _initialise_data_dir(self) -> None:
        """Create data directory and default files if they don't exist."""
        self._data_dir.mkdir(parents=True, exist_ok=True)
        (self._data_dir / "certs").mkdir(exist_ok=True)

        config_path = self._data_dir / "config.json"
        if not config_path.exists():
            default_config: JsonDict = {
                "cloudflare_api_token": "",
                "cloudflare_zone_id": "",
                "base_domain": "",
                "admin_key": secrets.token_urlsafe(32),
                "port": 8443,
            }
            self._write_json(config_path, default_config)

        domains_path = self._data_dir / "domains.json"
        if not domains_path.exists():
            self._write_json(domains_path, {"domains": []})

    # ------------------------------------------------------------------------------------
    def _read_json(self, path: pathlib.Path) -> JsonDict:
        """Read and parse a JSON file."""
        with self._lock:
            return json.loads(path.read_text())  # pyright: ignore[reportReturnType]

    # ------------------------------------------------------------------------------------
    def _write_json(self, path: pathlib.Path, data: JsonDict) -> None:
        """Write data to a JSON file atomically."""
        with self._lock:
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, indent=2) + "\n")
            tmp.rename(path)

    # ------------------------------------------------------------------------------------
    #   Config
    # ------------------------------------------------------------------------------------

    # ------------------------------------------------------------------------------------
    def get_config(self) -> JsonDict:
        """Read the configuration file."""
        return self._read_json(self._data_dir / "config.json")

    # ------------------------------------------------------------------------------------
    def save_config(self, config: JsonDict) -> None:
        """Write the configuration file."""
        self._write_json(self._data_dir / "config.json", config)

    # ------------------------------------------------------------------------------------
    #   Admin auth
    # ------------------------------------------------------------------------------------

    # ------------------------------------------------------------------------------------
    def verify_admin_key(self, key: str) -> bool:
        """Verify the admin login key."""
        config = self.get_config()
        return key == config.get("admin_key", "")

    # ------------------------------------------------------------------------------------
    def create_session(self) -> str:
        """Create a new admin session token."""
        token = secrets.token_urlsafe(32)
        config = self.get_config()
        sessions: list[str] = config.get("sessions", [])  # pyright: ignore[reportAssignmentType]
        sessions.append(token)
        config["sessions"] = sessions
        self.save_config(config)
        return token

    # ------------------------------------------------------------------------------------
    def verify_session(self, token: str) -> bool:
        """Verify an admin session token."""
        config = self.get_config()
        sessions: list[str] = config.get("sessions", [])  # pyright: ignore[reportAssignmentType]
        return token in sessions

    # ------------------------------------------------------------------------------------
    #   Domains
    # ------------------------------------------------------------------------------------

    # ------------------------------------------------------------------------------------
    def get_domains(self) -> list[JsonDict]:
        """Return the list of managed domains."""
        data = self._read_json(self._data_dir / "domains.json")
        return data.get("domains", [])  # pyright: ignore[reportReturnType]

    # ------------------------------------------------------------------------------------
    def add_domain(self, subdomain: str, ip_address: str) -> JsonDict:
        """Add a new subdomain with a generated API token. Returns the domain entry."""
        data = self._read_json(self._data_dir / "domains.json")
        domains: list[JsonDict] = data.get("domains", [])  # pyright: ignore[reportAssignmentType]

        # Check for duplicates
        for d in domains:
            if d.get("subdomain") == subdomain:
                return d

        entry: JsonDict = {
            "subdomain": subdomain,
            "ip_address": ip_address,
            "status": "pending",
            "api_token": secrets.token_urlsafe(32),
            "added_at": datetime.datetime.now(datetime.UTC).isoformat(),
            "cert_expires_at": None,
            "last_error": None,
        }
        domains.append(entry)
        self._write_json(self._data_dir / "domains.json", {"domains": domains})
        return entry

    # ------------------------------------------------------------------------------------
    def update_domain(self, subdomain: str, updates: JsonDict) -> None:
        """Update fields on a domain entry."""
        data = self._read_json(self._data_dir / "domains.json")
        domains: list[JsonDict] = data.get("domains", [])  # pyright: ignore[reportAssignmentType]

        for d in domains:
            if d.get("subdomain") == subdomain:
                d.update(updates)
                break

        self._write_json(self._data_dir / "domains.json", {"domains": domains})

    # ------------------------------------------------------------------------------------
    def remove_domain(self, subdomain: str) -> None:
        """Remove a subdomain from management."""
        data = self._read_json(self._data_dir / "domains.json")
        domains: list[JsonDict] = data.get("domains", [])  # pyright: ignore[reportAssignmentType]
        domains = [d for d in domains if d.get("subdomain") != subdomain]
        self._write_json(self._data_dir / "domains.json", {"domains": domains})

    # ------------------------------------------------------------------------------------
    def rotate_domain_token(self, subdomain: str) -> str:
        """Generate a new API token for a domain. Returns the new token."""
        new_token = secrets.token_urlsafe(32)
        self.update_domain(subdomain, {"api_token": new_token})
        return new_token

    # ------------------------------------------------------------------------------------
    def verify_domain_token(self, subdomain: str, token: str) -> bool:
        """Verify an API token against a specific domain."""
        domains = self.get_domains()
        for d in domains:
            if d.get("subdomain") == subdomain and d.get("api_token") == token:
                return True
        return False

    # ------------------------------------------------------------------------------------
    #   Certificates
    # ------------------------------------------------------------------------------------

    # ------------------------------------------------------------------------------------
    def save_cert(
        self,
        subdomain: str,
        cert_pem: str,
        chain_pem: str,
        key_pem: str,
        expires_at: str,
    ) -> None:
        """Save certificate files for a subdomain."""
        cert_dir = self._data_dir / "certs" / subdomain
        cert_dir.mkdir(parents=True, exist_ok=True)

        cert_data: JsonDict = {
            "cert_pem": cert_pem,
            "chain_pem": chain_pem,
            "key_pem": key_pem,
            "expires_at": expires_at,
            "issued_at": datetime.datetime.now(datetime.UTC).isoformat(),
        }
        self._write_json(cert_dir / "cert.json", cert_data)

    # ------------------------------------------------------------------------------------
    def get_cert(self, subdomain: str) -> JsonDict | None:
        """Retrieve certificate data for a subdomain, or None if not found."""
        cert_path = self._data_dir / "certs" / subdomain / "cert.json"
        if not cert_path.exists():
            return None
        return self._read_json(cert_path)

    # ------------------------------------------------------------------------------------
    #   ACME Account
    # ------------------------------------------------------------------------------------

    # ------------------------------------------------------------------------------------
    def get_acme_account(self) -> JsonDict | None:
        """Retrieve the ACME account data, or None if not registered."""
        account_path = self._data_dir / "acme_account.json"
        if not account_path.exists():
            return None
        return self._read_json(account_path)

    # ------------------------------------------------------------------------------------
    def save_acme_account(self, account_data: JsonDict) -> None:
        """Save ACME account registration data."""
        self._write_json(self._data_dir / "acme_account.json", account_data)
