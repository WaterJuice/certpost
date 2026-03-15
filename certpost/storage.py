# ----------------------------------------------------------------------------------------
#   storage.py
#   ----------
#
#   JSON file storage for certpost. Manages configuration, certificates, and API
#   tokens in ~/.certpost/. All file writes are protected by a threading lock.
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

import hashlib
import json
import pathlib
import secrets
import threading
import time
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
                "namecheap_api_user": "",
                "namecheap_api_key": "",
                "namecheap_username": "",
                "namecheap_client_ip": "",
                "base_domain": "",
                "acme_email": "",
                "acme_directory": "https://acme-v02.api.letsencrypt.org/directory",
                "port": 8443,
            }
            self._write_json(config_path, default_config)

        tokens_path = self._data_dir / "tokens.json"
        if not tokens_path.exists():
            self._write_json(tokens_path, {"tokens": []})

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
    #   Domains
    # ------------------------------------------------------------------------------------

    # ------------------------------------------------------------------------------------
    def get_domains(self) -> list[JsonDict]:
        """Return the list of managed domains."""
        data = self._read_json(self._data_dir / "domains.json")
        return data.get("domains", [])  # pyright: ignore[reportReturnType]

    # ------------------------------------------------------------------------------------
    def add_domain(self, subdomain: str) -> JsonDict:
        """Add a new subdomain to manage. Returns the domain entry."""
        data = self._read_json(self._data_dir / "domains.json")
        domains: list[JsonDict] = data.get("domains", [])  # pyright: ignore[reportAssignmentType]

        # Check for duplicates
        for d in domains:
            if d.get("subdomain") == subdomain:
                return d

        entry: JsonDict = {
            "subdomain": subdomain,
            "status": "pending",
            "added_at": time.time(),
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
    #   Tokens
    # ------------------------------------------------------------------------------------

    # ------------------------------------------------------------------------------------
    def get_tokens(self) -> list[JsonDict]:
        """Return the list of API tokens (hashed)."""
        data = self._read_json(self._data_dir / "tokens.json")
        return data.get("tokens", [])  # pyright: ignore[reportReturnType]

    # ------------------------------------------------------------------------------------
    def create_token(self, label: str) -> str:
        """Create a new API token. Returns the plaintext token (only shown once)."""
        token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(token.encode()).hexdigest()

        data = self._read_json(self._data_dir / "tokens.json")
        tokens: list[JsonDict] = data.get("tokens", [])  # pyright: ignore[reportAssignmentType]
        tokens.append(
            {
                "label": label,
                "hash": token_hash,
                "created_at": time.time(),
            }
        )
        self._write_json(self._data_dir / "tokens.json", {"tokens": tokens})
        return token

    # ------------------------------------------------------------------------------------
    def verify_token(self, token: str) -> bool:
        """Verify a bearer token against stored hashes."""
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        tokens = self.get_tokens()
        return any(t.get("hash") == token_hash for t in tokens)

    # ------------------------------------------------------------------------------------
    def revoke_token(self, token_hash: str) -> None:
        """Revoke a token by its hash."""
        data = self._read_json(self._data_dir / "tokens.json")
        tokens: list[JsonDict] = data.get("tokens", [])  # pyright: ignore[reportAssignmentType]
        tokens = [t for t in tokens if t.get("hash") != token_hash]
        self._write_json(self._data_dir / "tokens.json", {"tokens": tokens})

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
        expires_at: float,
    ) -> None:
        """Save certificate files for a subdomain."""
        cert_dir = self._data_dir / "certs" / subdomain
        cert_dir.mkdir(parents=True, exist_ok=True)

        cert_data: JsonDict = {
            "cert_pem": cert_pem,
            "chain_pem": chain_pem,
            "key_pem": key_pem,
            "expires_at": expires_at,
            "issued_at": time.time(),
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
