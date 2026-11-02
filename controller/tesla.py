"""Tesla Fleet API access.

Unsigned REST calls (vehicle state, wake_up) go direct; charging commands are
signed by `tesla-control` over the internet transport. Every call is counted
for the billing estimate.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time

import requests

AUTH_URL = "https://fleet-auth.prd.vn.cloud.tesla.com/oauth2/v3/token"
API_BASE = "https://fleet-api.prd.na.vn.cloud.tesla.com"  # North America + Asia-Pacific

# Approximate USD rates from developer.tesla.com.
RATES = {"data": 1 / 500, "commands": 1 / 1000, "wakes": 1 / 50}

# Command-response reasons reported by the car.
OK_REASONS = {"is_charging": "start", "not_charging": "stop"}
UNAVAILABLE_REASONS = ("disconnected", "complete", "no_power", "requested")


class TeslaError(RuntimeError):
    pass


def refresh_tokens(client_id: str, refresh_token: str) -> dict:
    r = requests.post(
        AUTH_URL,
        data={"grant_type": "refresh_token", "client_id": client_id, "refresh_token": refresh_token},
        timeout=30,
    )
    if r.status_code == 401:
        raise TeslaError("Tesla refresh token rejected (login_required): re-run scripts/tesla_setup.py auth")
    r.raise_for_status()
    ts = r.json()
    return {
        "access_token": ts["access_token"],
        "refresh_token": ts["refresh_token"],
        "expires_at": int(time.time()) + int(ts["expires_in"]) - 120,
    }


class Tesla:
    def __init__(self, client_id: str, tokens: dict, vin: str, private_key_pem: str, billing: dict, on_tokens_rotated):
        self.client_id = client_id
        self.tokens = tokens
        self.vin = vin
        self.private_key_pem = private_key_pem
        self.billing = billing
        self.on_tokens_rotated = on_tokens_rotated

    def _count(self, kind: str) -> None:
        self.billing[kind] = self.billing.get(kind, 0) + 1

    def _token(self) -> str:
        if self.tokens["expires_at"] <= time.time():
            self.tokens = refresh_tokens(self.client_id, self.tokens["refresh_token"])
            self.on_tokens_rotated(json.dumps(self.tokens))
            print("Tesla token refreshed and saved")
        return self.tokens["access_token"]

    def _get_state(self) -> str:
        r = requests.get(
            f"{API_BASE}/api/1/vehicles/{self.vin}",
            headers={"Authorization": f"Bearer {self._token()}"},
            timeout=30,
        )
        if r.status_code < 500:
            self._count("data")
        r.raise_for_status()
        return r.json()["response"]["state"]

    def is_online(self) -> bool:
        return self._get_state() == "online"

    def wake(self, timeout_s: int = 60) -> bool:
        r = requests.post(
            f"{API_BASE}/api/1/vehicles/{self.vin}/wake_up",
            headers={"Authorization": f"Bearer {self._token()}"},
            timeout=30,
        )
        if r.status_code < 500:
            self._count("wakes")
        r.raise_for_status()
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            time.sleep(10)
            if self.is_online():
                return True
        return False

    def command(self, *args: str) -> tuple[bool, str]:
        """Run a signed command. Returns (ok, reason). reason is the car's error text if any."""
        token = self._token()
        with tempfile.TemporaryDirectory() as d:
            key_path = os.path.join(d, "key.pem")
            tok_path = os.path.join(d, "token")
            with open(key_path, "w") as f:
                f.write(self.private_key_pem)
            with open(tok_path, "w") as f:
                f.write(token)
            env = {
                **os.environ,
                "TESLA_KEY_FILE": key_path,
                "TESLA_TOKEN_FILE": tok_path,
                "TESLA_VIN": self.vin,
                # Session cache stays in the temp dir: it is not persisted to the shared Actions cache.
                "TESLA_CACHE_FILE": os.path.join(d, "cache.json"),
            }
            p = subprocess.run(["tesla-control", *args], env=env, capture_output=True, text=True, timeout=120)
        self._count("commands")
        out = (p.stdout + p.stderr).strip()
        if p.returncode == 0:
            return True, ""
        for reason in (*OK_REASONS, *UNAVAILABLE_REASONS):
            if reason in out:
                return False, reason
        # Never echo raw output: it can contain the VIN.
        return False, "unknown_error"


def cost_usd(billing: dict) -> float:
    return sum(billing.get(k, 0) * rate for k, rate in RATES.items())
