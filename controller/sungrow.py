"""Minimal iSolarCloud OpenAPI client (Australian gateway).

Request format follows the pysolarcloud package (v0.5.0): POST JSON with
appkey + lang in the body, x-access-key and Bearer token in the headers.
"""

from __future__ import annotations

import json
import time

import requests

AU_GATEWAY = "https://augateway.isolarcloud.com"
AU_AUTH_WEB = "https://auweb3.isolarcloud.com"
AU_CLOUD_ID = 7


class SungrowError(RuntimeError):
    pass


def _unwrap(body: dict) -> dict:
    """Token endpoints may return fields at top level or inside result_data."""
    if "access_token" in body:
        return body
    data = body.get("result_data") or {}
    if "access_token" in data:
        return data
    raise SungrowError(f"token response missing access_token (result_code={body.get('result_code')})")


def tokens_from_response(body: dict) -> dict:
    ts = _unwrap(body)
    return {
        "access_token": ts["access_token"],
        "refresh_token": ts["refresh_token"],
        "expires_at": int(time.time()) + int(ts["expires_in"]) - 60,
    }


class Sungrow:
    def __init__(self, appkey: str, secret_key: str, tokens: dict, on_tokens_rotated):
        self.appkey = appkey
        self.secret_key = secret_key
        self.tokens = tokens
        self.on_tokens_rotated = on_tokens_rotated

    def _refresh_if_needed(self) -> None:
        if self.tokens["expires_at"] > time.time():
            return
        r = requests.post(
            f"{AU_GATEWAY}/openapi/apiManage/refreshToken",
            headers={"x-access-key": self.secret_key},
            json={"appkey": self.appkey, "refresh_token": self.tokens["refresh_token"]},
            timeout=30,
        )
        r.raise_for_status()
        self.tokens = tokens_from_response(r.json())
        # Save before use: the old refresh token may already be invalid.
        self.on_tokens_rotated(json.dumps(self.tokens))
        print("iSolarCloud token refreshed and saved")

    def pv_power_w(self, plant_id: str, point_id: str) -> float | None:
        self._refresh_if_needed()
        r = requests.post(
            f"{AU_GATEWAY}/openapi/platform/getPowerStationRealTimeData",
            headers={"x-access-key": self.secret_key, "Authorization": f"Bearer {self.tokens['access_token']}"},
            json={
                "appkey": self.appkey,
                "lang": "_en_US",
                "ps_id_list": [plant_id],
                "point_id_list": [point_id],
                "is_get_point_dict": "1",
            },
            timeout=30,
        )
        r.raise_for_status()
        body = r.json()
        if body.get("result_code") != "1":
            raise SungrowError(f"realtime data error result_code={body.get('result_code')} msg={body.get('result_msg')}")
        plants = body["result_data"]["device_point_list"]
        if not plants:
            return None
        raw = plants[0].get(f"p{point_id}")
        if raw in (None, "", "--"):
            return None
        return float(raw)
