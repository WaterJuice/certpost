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
import hashlib
import json
import pathlib
import secrets
import threading
from typing import Any

# ----------------------------------------------------------------------------------------
#   Constants
# ----------------------------------------------------------------------------------------

_TOKEN_CHARS = "abcdefghijklmnopqrstuvwxyz0123456789"
_TOKEN_LENGTH = 40

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

    def __init__(self, data_dir: str) -> None:
        """Initialise storage with the given data directory."""
        self._data_dir = pathlib.Path(data_dir)
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
                "base_domain": "",
                "admin_key": "".join(
                    secrets.choice(_TOKEN_CHARS) for _ in range(_TOKEN_LENGTH)
                ),
                "port": 8443,
                "dns": {
                    "provider": "cloudflare",
                    "api_token": "",
                    "zone_id": "",
                },
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
        """Read the configuration file.

        Automatically migrates legacy flat Cloudflare configs to the new
        ``dns_acme`` / ``dns_records`` structure on first read.
        """
        config = self._read_json(self._data_dir / "config.json")
        if "cloudflare_api_token" in config and "dns" not in config:
            config = self._migrate_legacy_config(config)
        return config

    # ------------------------------------------------------------------------------------
    def _migrate_legacy_config(self, config: JsonDict) -> JsonDict:
        """Convert a legacy flat Cloudflare config to the new provider format."""
        config["dns"] = {
            "provider": "cloudflare",
            "api_token": config.pop("cloudflare_api_token", ""),
            "zone_id": config.pop("cloudflare_zone_id", ""),
        }
        self._write_json(self._data_dir / "config.json", config)
        return config

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
    def admin_cookie_value(self) -> str:
        """Return a SHA-256 hash of the admin key for use as a session cookie."""
        config = self.get_config()
        admin_key: str = config.get("admin_key", "")  # pyright: ignore[reportAssignmentType]
        return hashlib.sha256(admin_key.encode()).hexdigest()

    # ------------------------------------------------------------------------------------
    def verify_admin_cookie(self, value: str) -> bool:
        """Verify an admin session cookie value."""
        return value == self.admin_cookie_value()

    # ------------------------------------------------------------------------------------
    #   Domains
    # ------------------------------------------------------------------------------------

    # ------------------------------------------------------------------------------------
    def get_domains(self) -> list[JsonDict]:
        """Return the list of managed domains."""
        data = self._read_json(self._data_dir / "domains.json")
        return data.get("domains", [])  # pyright: ignore[reportReturnType]

    # ------------------------------------------------------------------------------------
    def add_domain(self, subdomain: str, target: str) -> JsonDict:
        """Add a new subdomain with a generated API token. Returns the domain entry."""
        data = self._read_json(self._data_dir / "domains.json")
        domains: list[JsonDict] = data.get("domains", [])  # pyright: ignore[reportAssignmentType]

        # Check for duplicates
        for d in domains:
            if d.get("subdomain") == subdomain:
                return d

        entry: JsonDict = {
            "subdomain": subdomain,
            "target": target,
            "status": "pending",
            "api_token": "".join(
                secrets.choice(_TOKEN_CHARS) for _ in range(_TOKEN_LENGTH)
            ),
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
        new_token = "".join(secrets.choice(_TOKEN_CHARS) for _ in range(_TOKEN_LENGTH))
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
