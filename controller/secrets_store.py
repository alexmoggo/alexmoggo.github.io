"""Write rotated tokens back to GitHub Actions secrets.

Uses the REST endpoint "Create or update a repository secret". The token in
GH_SECRETS_PAT must be a fine-grained PAT with "Secrets" repository permission (write).
"""

from __future__ import annotations

import base64
import os

import requests
from nacl import encoding, public

API = "https://api.github.com"


def update_secret(name: str, value: str) -> None:
    pat = os.environ.get("GH_SECRETS_PAT")
    repo = os.environ.get("GITHUB_REPOSITORY")
    if not pat or not repo:
        raise RuntimeError("GH_SECRETS_PAT and GITHUB_REPOSITORY are required to save rotated tokens")
    headers = {
        "Authorization": f"Bearer {pat}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    r = requests.get(f"{API}/repos/{repo}/actions/secrets/public-key", headers=headers, timeout=30)
    r.raise_for_status()
    key = r.json()
    box = public.SealedBox(public.PublicKey(key["key"].encode(), encoding.Base64Encoder()))
    encrypted = base64.b64encode(box.encrypt(value.encode())).decode()
    r = requests.put(
        f"{API}/repos/{repo}/actions/secrets/{name}",
        headers=headers,
        json={"encrypted_value": encrypted, "key_id": key["key_id"]},
        timeout=30,
    )
    r.raise_for_status()
