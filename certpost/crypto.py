# ----------------------------------------------------------------------------------------
#   crypto.py
#   ---------
#
#   OpenSSL subprocess wrappers for key generation, CSR creation, and JWS signing.
#   Uses system openssl binary — no pip dependencies required.
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

import base64
import hashlib
import json
import subprocess
import tempfile
from typing import Any

# ----------------------------------------------------------------------------------------
#   Types
# ----------------------------------------------------------------------------------------

type JsonDict = dict[str, Any]

# ----------------------------------------------------------------------------------------
#   Functions
# ----------------------------------------------------------------------------------------


# ----------------------------------------------------------------------------------------
def _b64url(data: bytes) -> str:
    """Base64url-encode without padding."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


# ----------------------------------------------------------------------------------------
def generate_rsa_key(bits: int = 4096) -> str:
    """Generate an RSA private key using openssl. Returns PEM string."""
    result = subprocess.run(
        ["openssl", "genrsa", str(bits)],
        capture_output=True,
        check=True,
        text=True,
    )
    return result.stdout


# ----------------------------------------------------------------------------------------
def generate_ec_key() -> str:
    """Generate an EC private key (P-256) using openssl. Returns PEM string."""
    result = subprocess.run(
        ["openssl", "ecparam", "-genkey", "-name", "prime256v1", "-noout"],
        capture_output=True,
        check=True,
        text=True,
    )
    return result.stdout


# ----------------------------------------------------------------------------------------
def create_csr(key_pem: str, domains: list[str]) -> str:
    """Create a CSR for the given domains using the provided private key. Returns PEM string."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".pem", delete=False) as key_file:
        key_file.write(key_pem)
        key_path = key_file.name

    # Build SAN extension
    san_entries = ", ".join(f"DNS:{d}" for d in domains)
    san_config = f"[req]\nreq_extensions = v3_req\ndistinguished_name = req_distinguished_name\n[req_distinguished_name]\n[v3_req]\nsubjectAltName = {san_entries}\n"

    with tempfile.NamedTemporaryFile(mode="w", suffix=".cnf", delete=False) as cnf_file:
        cnf_file.write(san_config)
        cnf_path = cnf_file.name

    try:
        result = subprocess.run(
            [
                "openssl",
                "req",
                "-new",
                "-key",
                key_path,
                "-subj",
                f"/CN={domains[0]}",
                "-config",
                cnf_path,
            ],
            capture_output=True,
            check=True,
            text=True,
        )
        return result.stdout
    finally:
        import os

        os.unlink(key_path)
        os.unlink(cnf_path)


# ----------------------------------------------------------------------------------------
def get_rsa_public_numbers(key_pem: str) -> tuple[str, str]:
    """Extract RSA public key modulus (n) and exponent (e) as base64url strings."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".pem", delete=False) as key_file:
        key_file.write(key_pem)
        key_path = key_file.name

    try:
        result = subprocess.run(
            ["openssl", "rsa", "-in", key_path, "-noout", "-text"],
            capture_output=True,
            check=True,
            text=True,
        )
        output = result.stdout

        # Parse modulus
        lines = output.split("\n")
        modulus_hex = ""
        exponent = 0
        in_modulus = False

        for line in lines:
            if "modulus:" in line.lower():
                in_modulus = True
                continue
            if "exponent:" in line.lower():
                in_modulus = False
                # Extract exponent value
                parts = line.split("(")
                if len(parts) >= 1:
                    exp_str = parts[0].split(":")[1].strip()
                    exponent = int(exp_str)
                continue
            if in_modulus:
                stripped = line.strip().replace(":", "")
                if stripped and all(c in "0123456789abcdef" for c in stripped):
                    modulus_hex += stripped

        # Convert modulus hex to bytes
        mod_bytes = bytes.fromhex(modulus_hex)
        # Remove leading zero if present
        if mod_bytes[0:1] == b"\x00":
            mod_bytes = mod_bytes[1:]

        # Convert exponent to bytes
        exp_bytes = exponent.to_bytes((exponent.bit_length() + 7) // 8, byteorder="big")

        return _b64url(mod_bytes), _b64url(exp_bytes)
    finally:
        import os

        os.unlink(key_path)


# ----------------------------------------------------------------------------------------
def sign_rs256(key_pem: str, data: bytes) -> bytes:
    """Sign data using RS256 (RSASSA-PKCS1-v1_5 with SHA-256). Returns raw signature bytes."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".pem", delete=False) as key_file:
        key_file.write(key_pem)
        key_path = key_file.name

    with tempfile.NamedTemporaryFile(suffix=".dat", delete=False) as data_file:
        data_file.write(data)
        data_path = data_file.name

    try:
        result = subprocess.run(
            ["openssl", "dgst", "-sha256", "-sign", key_path, data_path],
            capture_output=True,
            check=True,
        )
        return result.stdout
    finally:
        import os

        os.unlink(key_path)
        os.unlink(data_path)


# ----------------------------------------------------------------------------------------
def build_jws(
    url: str,
    payload: JsonDict | str,
    nonce: str,
    account_key_pem: str,
    kid: str | None = None,
) -> str:
    """Build a JWS (JSON Web Signature) for ACME requests."""
    # Header
    header: JsonDict = {"alg": "RS256", "nonce": nonce, "url": url}
    if kid:
        header["kid"] = kid
    else:
        # Use JWK for initial registration
        n, e = get_rsa_public_numbers(account_key_pem)
        header["jwk"] = {"kty": "RSA", "n": n, "e": e}

    header_b64 = _b64url(json.dumps(header).encode())

    # Payload
    if payload == "":
        payload_b64 = ""
    else:
        payload_b64 = _b64url(json.dumps(payload).encode())

    # Signature
    signing_input = f"{header_b64}.{payload_b64}".encode()
    signature = sign_rs256(account_key_pem, signing_input)
    sig_b64 = _b64url(signature)

    return json.dumps(
        {
            "protected": header_b64,
            "payload": payload_b64,
            "signature": sig_b64,
        }
    )


# ----------------------------------------------------------------------------------------
def thumbprint(account_key_pem: str) -> str:
    """Compute the JWK thumbprint (SHA-256) of an RSA account key."""
    n, e = get_rsa_public_numbers(account_key_pem)
    jwk_json = json.dumps(
        {"e": e, "kty": "RSA", "n": n}, separators=(",", ":"), sort_keys=True
    )
    return _b64url(hashlib.sha256(jwk_json.encode()).digest())


# ----------------------------------------------------------------------------------------
def dns_challenge_value(token: str, account_key_pem: str) -> str:
    """Compute the DNS-01 challenge value for a given token and account key."""
    tp = thumbprint(account_key_pem)
    key_auth = f"{token}.{tp}"
    return _b64url(hashlib.sha256(key_auth.encode()).digest())


# ----------------------------------------------------------------------------------------
def parse_cert_expiry(cert_pem: str) -> float:
    """Parse the expiry date from a PEM certificate. Returns Unix timestamp."""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".pem", delete=False
    ) as cert_file:
        cert_file.write(cert_pem)
        cert_path = cert_file.name

    try:
        result = subprocess.run(
            ["openssl", "x509", "-in", cert_path, "-noout", "-enddate"],
            capture_output=True,
            check=True,
            text=True,
        )
        # Output format: notAfter=Mon DD HH:MM:SS YYYY GMT
        date_str = result.stdout.strip().split("=", 1)[1]

        import email.utils

        parsed = email.utils.parsedate(date_str)
        if parsed is None:
            raise ValueError(f"Could not parse certificate expiry date: {date_str}")

        import calendar

        return float(calendar.timegm(parsed))
    finally:
        import os

        os.unlink(cert_path)
