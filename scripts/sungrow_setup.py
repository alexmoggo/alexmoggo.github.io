"""One-off iSolarCloud setup, run on your own computer (not in Actions).

  python scripts/sungrow_setup.py

Reads SUNGROW_APPKEY, SUNGROW_SECRET_KEY and SUNGROW_APP_ID from the environment.
Signs in, prints the SUNGROW_TOKENS secret value, lists your plant ID(s), and shows the
candidate PV power readings so you can compare them with the iSolarCloud app.
Prints secrets to your terminal only; paste them into GitHub secrets, then clear the terminal.
"""

import json
import os
import sys
from urllib.parse import parse_qs, quote_plus, urlparse

import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from controller.sungrow import AU_AUTH_WEB, AU_CLOUD_ID, AU_GATEWAY, tokens_from_response  # noqa: E402

REDIRECT_URI = "https://alexmoggo.github.io/"
CANDIDATE_POINTS = {"83033": "plant power", "83002": "inverter AC power"}


def main():
    try:
        appkey, secret, app_id = (os.environ[k] for k in ("SUNGROW_APPKEY", "SUNGROW_SECRET_KEY", "SUNGROW_APP_ID"))
    except KeyError:
        sys.exit("Set SUNGROW_APPKEY, SUNGROW_SECRET_KEY and SUNGROW_APP_ID first")
    url = (f"{AU_AUTH_WEB}/#/authorized-app?cloudId={AU_CLOUD_ID}"
           f"&applicationId={app_id}&redirectUrl={quote_plus(REDIRECT_URI)}")
    print("Open this URL, sign in, approve, then copy the full address you land on:\n\n" + url + "\n")
    code = parse_qs(urlparse(input("Paste the full redirected URL: ").strip()).query)["code"][0]

    r = requests.post(f"{AU_GATEWAY}/openapi/apiManage/token", headers={"x-access-key": secret}, json={
        "appkey": appkey, "code": code, "grant_type": "authorization_code", "redirect_uri": REDIRECT_URI,
    }, timeout=30)
    r.raise_for_status()
    tokens = tokens_from_response(r.json())
    print("\nSUNGROW_TOKENS secret value:\n\n" + json.dumps(tokens) + "\n")

    h = {"x-access-key": secret, "Authorization": f"Bearer {tokens['access_token']}"}
    r = requests.post(f"{AU_GATEWAY}/openapi/platform/queryPowerStationList", headers=h,
                      json={"appkey": appkey, "lang": "_en_US", "page": 1, "size": 10}, timeout=30)
    r.raise_for_status()
    plants = r.json().get("result_data", {}).get("pageList", [])
    for p in plants:
        print(f"SUNGROW_PLANT_ID candidate: {p.get('ps_id')}  ({p.get('ps_name')})")
    if not plants:
        print("No plants returned. Raw result_code:", r.json().get("result_code"))
        return

    r = requests.post(f"{AU_GATEWAY}/openapi/platform/getPowerStationRealTimeData", headers=h, json={
        "appkey": appkey, "lang": "_en_US", "ps_id_list": [str(plants[0]["ps_id"])],
        "point_id_list": list(CANDIDATE_POINTS), "is_get_point_dict": "1",
    }, timeout=30)
    r.raise_for_status()
    row = (r.json().get("result_data", {}).get("device_point_list") or [{}])[0]
    print("\nCompare with current power in the iSolarCloud app:")
    for pid, name in CANDIDATE_POINTS.items():
        print(f"  {pid} {name}: {row.get('p' + pid)} W")


if __name__ == "__main__":
    main()
