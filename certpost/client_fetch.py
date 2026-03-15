# ----------------------------------------------------------------------------------------
#   client_fetch.py
#   ---------------
#
#   Certificate fetching and saving logic shared between the client CLI and proxy.
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
import pathlib
import urllib.error
import urllib.request
from typing import Any

# ----------------------------------------------------------------------------------------
#   Types
# ----------------------------------------------------------------------------------------

type JsonDict = dict[str, Any]

# ----------------------------------------------------------------------------------------
#   Functions
# ----------------------------------------------------------------------------------------


# ----------------------------------------------------------------------------------------
def fetch_cert(server_url: str, token: str, domain: str) -> JsonDict:
    """Fetch certificate data from a certpost server."""
    url = f"{server_url.rstrip('/')}/api/cert/{domain}"
    req = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {token}"},
        method="GET",
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            return json.loads(response.read())  # pyright: ignore[reportReturnType]
    except urllib.error.HTTPError as e:
        error_body = e.read().decode()
        raise RuntimeError(f"Server returned {e.code}: {error_body}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"Could not connect to server: {e.reason}") from e


# ----------------------------------------------------------------------------------------
def save_cert(output_dir: pathlib.Path, domain: str, cert_data: JsonDict) -> None:
    """Save certificate files to disk."""
    output_dir.mkdir(parents=True, exist_ok=True)

    cert_path = output_dir / f"{domain}.crt.pem"
    key_path = output_dir / f"{domain}.key.pem"

    cert_pem = cert_data.get("cert_pem", "")
    chain_pem = cert_data.get("chain_pem", "")
    key_pem = cert_data.get("key_pem", "")

    cert_path.write_text(cert_pem + chain_pem)
    key_path.write_text(key_pem)
    key_path.chmod(0o600)

    print(f"Wrote public cert to {cert_path}")
    print(f"Wrote private key to {key_path}")
