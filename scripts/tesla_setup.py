"""One-off Tesla setup, run on your own computer (not in Actions).

  python scripts/tesla_setup.py register   # register domain with Fleet API (once)
  python scripts/tesla_setup.py auth       # sign in and print the TESLA_TOKENS secret value

Reads TESLA_CLIENT_ID and TESLA_CLIENT_SECRET from the environment.
Prints secrets to your terminal only; paste them into GitHub secrets, then clear the terminal.
"""

import json
import os
import secrets
import sys
import time
from urllib.parse import parse_qs, urlencode, urlparse

import requests

DOMAIN = "alexmoggo.github.io"
REDIRECT_URI = f"https://{DOMAIN}/"
AUDIENCE = "https://fleet-api.prd.na.vn.cloud.tesla.com"
TOKEN_URL = "https://fleet-auth.prd.vn.cloud.tesla.com/oauth2/v3/token"
SCOPES = "openid offline_access vehicle_device_data vehicle_cmds vehicle_charging_cmds"


def creds():
    try:
        return os.environ["TESLA_CLIENT_ID"], os.environ["TESLA_CLIENT_SECRET"]
    except KeyError:
        sys.exit("Set TESLA_CLIENT_ID and TESLA_CLIENT_SECRET first")


def register():
    cid, secret = creds()
    r = requests.post(TOKEN_URL, data={
        "grant_type": "client_credentials", "client_id": cid, "client_secret": secret,
        "scope": "openid vehicle_device_data vehicle_cmds vehicle_charging_cmds", "audience": AUDIENCE,
    }, timeout=30)
    r.raise_for_status()
    partner = r.json()["access_token"]
    r = requests.post(f"{AUDIENCE}/api/1/partner_accounts",
                      headers={"Authorization": f"Bearer {partner}"}, json={"domain": DOMAIN}, timeout=30)
    print(r.status_code, r.text)


def auth():
    cid, secret = creds()
    state = secrets.token_urlsafe(16)
    url = "https://auth.tesla.com/oauth2/v3/authorize?" + urlencode({
        "client_id": cid, "locale": "en-US", "prompt": "login", "redirect_uri": REDIRECT_URI,
        "response_type": "code", "scope": SCOPES, "state": state,
    })
    print("Open this URL, sign in, approve, then copy the full address you land on:\n\n" + url + "\n")
    q = parse_qs(urlparse(input("Paste the full redirected URL: ").strip()).query)
    if q.get("state", [""])[0] != state:
        sys.exit("state mismatch, aborting")
    r = requests.post(TOKEN_URL, data={
        "grant_type": "authorization_code", "client_id": cid, "client_secret": secret,
        "code": q["code"][0], "audience": AUDIENCE, "redirect_uri": REDIRECT_URI,
    }, timeout=30)
    r.raise_for_status()
    ts = r.json()
    print("\nTESLA_TOKENS secret value:\n")
    print(json.dumps({"access_token": ts["access_token"], "refresh_token": ts["refresh_token"],
                      "expires_at": int(time.time()) + int(ts["expires_in"]) - 120}))


if __name__ == "__main__":
    {"register": register, "auth": auth}.get(sys.argv[1] if len(sys.argv) > 1 else "", lambda: sys.exit(__doc__))()
