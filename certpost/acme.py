# ----------------------------------------------------------------------------------------
#   acme.py
#   -------
#
#   ACME v2 client for Let's Encrypt certificate issuance using DNS-01 challenges.
#   Uses urllib.request for HTTP and shells out to openssl for all crypto operations.
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
import sys
import time
import urllib.error
import urllib.request
from typing import Any
from .crypto import build_jws
from .crypto import create_csr
from .crypto import dns_challenge_value
from .crypto import generate_rsa_key
from .crypto import parse_cert_expiry
from .namecheap import NamecheapClient
from .storage import Storage

# ----------------------------------------------------------------------------------------
#   Types
# ----------------------------------------------------------------------------------------

type JsonDict = dict[str, Any]

# ----------------------------------------------------------------------------------------
#   Constants
# ----------------------------------------------------------------------------------------

_DNS_PROPAGATION_WAIT = 30
_CHALLENGE_POLL_INTERVAL = 2
_CHALLENGE_POLL_TIMEOUT = 120
_ORDER_POLL_INTERVAL = 2
_ORDER_POLL_TIMEOUT = 120

# ----------------------------------------------------------------------------------------
#   ACME Client
# ----------------------------------------------------------------------------------------


# ----------------------------------------------------------------------------------------
class AcmeClient:
    """ACME v2 client for Let's Encrypt."""

    # ------------------------------------------------------------------------------------
    #   Construction
    # ------------------------------------------------------------------------------------

    def __init__(self, storage: Storage, namecheap: NamecheapClient) -> None:
        """Initialise the ACME client."""
        self._storage = storage
        self._namecheap = namecheap
        self._directory: JsonDict = {}
        self._account_key_pem: str = ""
        self._account_kid: str = ""

    # ------------------------------------------------------------------------------------
    #   Private methods
    # ------------------------------------------------------------------------------------

    # ------------------------------------------------------------------------------------
    def _log(self, message: str) -> None:
        """Log a message to stderr."""
        print(f"  [acme] {message}", file=sys.stderr)

    # ------------------------------------------------------------------------------------
    def _fetch_directory(self) -> None:
        """Fetch the ACME directory endpoints."""
        config = self._storage.get_config()
        directory_url = config.get(
            "acme_directory", "https://acme-v02.api.letsencrypt.org/directory"
        )
        with urllib.request.urlopen(str(directory_url), timeout=30) as response:
            self._directory = json.loads(response.read())

    # ------------------------------------------------------------------------------------
    def _get_nonce(self) -> str:
        """Get a fresh nonce from the ACME server."""
        nonce_url = self._directory["newNonce"]
        req = urllib.request.Request(str(nonce_url), method="HEAD")
        with urllib.request.urlopen(req, timeout=30) as response:
            nonce = response.headers.get("Replay-Nonce", "")
            return str(nonce)

    # ------------------------------------------------------------------------------------
    def _acme_request(
        self, url: str, payload: JsonDict | str
    ) -> tuple[JsonDict, dict[str, str]]:
        """Make a signed ACME request. Returns (response_body, response_headers)."""
        nonce = self._get_nonce()

        kid = self._account_kid if self._account_kid else None
        body = build_jws(url, payload, nonce, self._account_key_pem, kid=kid)

        req = urllib.request.Request(
            url,
            data=body.encode(),
            headers={"Content-Type": "application/jose+json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                resp_body = response.read()
                headers = {k.lower(): v for k, v in response.headers.items()}
                if resp_body:
                    return json.loads(resp_body), headers
                return {}, headers
        except urllib.error.HTTPError as e:
            error_body = e.read().decode()
            raise RuntimeError(f"ACME request failed ({e.code}): {error_body}") from e

    # ------------------------------------------------------------------------------------
    def _ensure_account(self) -> None:
        """Ensure we have an ACME account registered."""
        account = self._storage.get_acme_account()

        if account and account.get("key_pem") and account.get("kid"):
            self._account_key_pem = str(account["key_pem"])
            self._account_kid = str(account["kid"])
            return

        # Generate account key if needed
        if account and account.get("key_pem"):
            self._account_key_pem = str(account["key_pem"])
        else:
            self._log("Generating ACME account key...")
            self._account_key_pem = generate_rsa_key(4096)

        # Register account
        config = self._storage.get_config()
        email = config.get("acme_email", "")

        self._log("Registering ACME account...")
        payload: JsonDict = {
            "termsOfServiceAgreed": True,
        }
        if email:
            payload["contact"] = [f"mailto:{email}"]

        new_account_url = self._directory["newAccount"]
        _, headers = self._acme_request(str(new_account_url), payload)

        self._account_kid = headers.get("location", "")
        if not self._account_kid:
            raise RuntimeError("ACME registration did not return account URL")

        self._storage.save_acme_account(
            {
                "key_pem": self._account_key_pem,
                "kid": self._account_kid,
            }
        )
        self._log(f"Account registered: {self._account_kid}")

    # ------------------------------------------------------------------------------------
    #   Public methods
    # ------------------------------------------------------------------------------------

    # ------------------------------------------------------------------------------------
    def initialise(self) -> None:
        """Initialise the ACME client — fetch directory and ensure account exists."""
        self._fetch_directory()
        self._ensure_account()

    # ------------------------------------------------------------------------------------
    def issue_certificate(self, fqdn: str) -> JsonDict:
        """Issue a certificate for the given FQDN. Returns cert data dict."""
        config = self._storage.get_config()
        base_domain = str(config.get("base_domain", ""))

        self._log(f"Ordering certificate for {fqdn}...")

        # Create order
        new_order_url = self._directory["newOrder"]
        order_payload: JsonDict = {
            "identifiers": [{"type": "dns", "value": fqdn}],
        }
        order, order_headers = self._acme_request(str(new_order_url), order_payload)
        order_url = order_headers.get("location", "")

        # Process authorisations
        authorisations: list[str] = order.get("authorizations", [])
        for auth_url in authorisations:
            auth_body, _ = self._acme_request(auth_url, "")
            challenges: list[JsonDict] = auth_body.get("challenges", [])

            # Find DNS-01 challenge
            dns_challenge: JsonDict | None = None
            for c in challenges:
                if c.get("type") == "dns-01":
                    dns_challenge = c
                    break

            if dns_challenge is None:
                raise RuntimeError(f"No DNS-01 challenge found for {fqdn}")

            token = str(dns_challenge["token"])
            challenge_url = str(dns_challenge["url"])
            challenge_value = dns_challenge_value(token, self._account_key_pem)

            # Set DNS TXT record
            acme_hostname = f"_acme-challenge.{fqdn}".replace(f".{base_domain}", "")
            self._log(f"Setting TXT record: {acme_hostname} = {challenge_value}")
            self._namecheap.set_txt_record(base_domain, acme_hostname, challenge_value)

            # Wait for DNS propagation
            self._log(f"Waiting {_DNS_PROPAGATION_WAIT}s for DNS propagation...")
            time.sleep(_DNS_PROPAGATION_WAIT)

            # Tell ACME server to validate
            self._log("Requesting challenge validation...")
            self._acme_request(challenge_url, {})

            # Poll for challenge completion
            start = time.time()
            while time.time() - start < _CHALLENGE_POLL_TIMEOUT:
                auth_body, _ = self._acme_request(auth_url, "")
                status = auth_body.get("status", "")
                if status == "valid":
                    self._log("Challenge validated!")
                    break
                if status == "invalid":
                    raise RuntimeError(f"Challenge failed for {fqdn}: {auth_body}")
                time.sleep(_CHALLENGE_POLL_INTERVAL)
            else:
                raise RuntimeError(f"Challenge timed out for {fqdn}")

            # Clean up DNS record
            self._log("Cleaning up TXT record...")
            self._namecheap.remove_txt_record(base_domain, acme_hostname)

        # Generate cert key and CSR
        self._log("Generating certificate key and CSR...")
        cert_key_pem = generate_rsa_key(2048)
        csr_pem = create_csr(cert_key_pem, [fqdn])

        # Finalise order
        import base64

        # Convert PEM CSR to DER for ACME
        csr_lines = [
            line
            for line in csr_pem.split("\n")
            if not line.startswith("-----") and line.strip()
        ]
        csr_der = base64.b64decode("".join(csr_lines))
        csr_b64 = base64.urlsafe_b64encode(csr_der).rstrip(b"=").decode("ascii")

        finalise_url = str(order.get("finalize", ""))
        self._log("Finalising order...")
        self._acme_request(finalise_url, {"csr": csr_b64})

        # Poll for certificate
        start = time.time()
        cert_url = ""
        while time.time() - start < _ORDER_POLL_TIMEOUT:
            order_body, _ = self._acme_request(order_url, "")
            status = order_body.get("status", "")
            if status == "valid":
                cert_url = str(order_body.get("certificate", ""))
                break
            if status == "invalid":
                raise RuntimeError(f"Order failed for {fqdn}: {order_body}")
            time.sleep(_ORDER_POLL_INTERVAL)
        else:
            raise RuntimeError(f"Order timed out for {fqdn}")

        # Download certificate
        self._log("Downloading certificate...")
        nonce = self._get_nonce()
        body = build_jws(
            cert_url, "", nonce, self._account_key_pem, kid=self._account_kid
        )
        req = urllib.request.Request(
            cert_url,
            data=body.encode(),
            headers={
                "Content-Type": "application/jose+json",
                "Accept": "application/pem-certificate-chain",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as response:
            full_chain = response.read().decode()

        # Split into cert and chain
        certs = full_chain.split("-----END CERTIFICATE-----")
        cert_pem = certs[0] + "-----END CERTIFICATE-----\n" if certs else ""
        chain_pem = (
            "-----END CERTIFICATE-----".join(certs[1:]).strip()
            if len(certs) > 1
            else ""
        )
        if chain_pem and not chain_pem.endswith("\n"):
            chain_pem += "\n"

        # Parse expiry
        expires_at = parse_cert_expiry(cert_pem)

        # Save
        self._storage.save_cert(fqdn, cert_pem, chain_pem, cert_key_pem, expires_at)
        self._storage.update_domain(
            fqdn,
            {
                "status": "issued",
                "cert_expires_at": expires_at,
                "last_error": None,
            },
        )

        self._log(f"Certificate issued for {fqdn}")

        return {
            "cert_pem": cert_pem,
            "chain_pem": chain_pem,
            "key_pem": cert_key_pem,
            "expires_at": expires_at,
        }
