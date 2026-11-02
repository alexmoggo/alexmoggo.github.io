"""One controller run. Invoked every 5 minutes by GitHub Actions.

Logs are public: never print the VIN, plant ID, tokens or raw API responses.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from . import decide
from .secrets_store import update_secret
from .sungrow import Sungrow, SungrowError
from .tesla import Tesla, TeslaError, cost_usd

TZ = ZoneInfo("Australia/Brisbane")
STATE_FILE = os.environ.get("STATE_FILE", ".state/state.json")
BACKOFF = {"disconnected": 60, "no_power": 30, "requested": 15, "unknown_error": 30, "wake_failed": 30}


def env(name: str, default: str | None = None) -> str:
    v = os.environ.get(name) or default
    if v is None:
        sys.exit(f"missing required setting {name}")
    return v


def load_state() -> dict:
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_state(state: dict) -> None:
    os.makedirs(os.path.dirname(STATE_FILE) or ".", exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=1)


def next_morning(now: datetime) -> datetime:
    return (now + timedelta(days=1)).replace(hour=6, minute=0, second=0, microsecond=0)


def apply_live(tesla: Tesla, action: decide.Action, state: dict, now: datetime) -> str:
    """Send the action to the car. Returns a short outcome string for the log."""
    if not tesla.is_online():
        if action.kind in ("stop", "set_amps"):
            # An asleep car is not charging: nothing to stop or adjust.
            state.update(charging=False, amps=0)
            return "car asleep, assumed not charging"
        if not tesla.wake():
            state["car_unavailable_until"] = (now + timedelta(minutes=BACKOFF["wake_failed"])).isoformat()
            return "wake failed"

    if action.kind == "start":
        ok, reason = tesla.command("charging-set-amps", str(action.amps))
        if ok:
            ok, reason = tesla.command("charging-start")
        if ok or reason == "is_charging":
            state.update(charging=True, amps=action.amps)
            return "started" if ok else "already charging"
    elif action.kind == "stop":
        ok, reason = tesla.command("charging-stop")
        if ok or reason == "not_charging":
            state.update(charging=False, amps=0)
            return "stopped" if ok else "already stopped"
    elif action.kind == "set_amps":
        ok, reason = tesla.command("charging-set-amps", str(action.amps))
        if ok:
            state["amps"] = action.amps
            return "amps set"
    else:
        return "nothing to do"

    state.update(charging=False, amps=0)
    until = next_morning(now) if reason == "complete" else now + timedelta(minutes=BACKOFF.get(reason, 30))
    state["car_unavailable_until"] = until.isoformat()
    return f"car reported {reason}, pausing until {until:%H:%M %d %b}"


def main() -> int:
    now = datetime.now(TZ)
    live = os.environ.get("CONTROLLER_LIVE", "").lower() == "true"
    cfg = decide.Config(
        house_load_w=float(env("HOUSE_LOAD_W", "1000")),
        min_amps=int(env("MIN_AMPS", "5")),
    )
    state = load_state()

    month = now.strftime("%Y-%m")
    if state.get("billing", {}).get("month") != month:
        state["billing"] = {"month": month}
    billing = state["billing"]

    pv_w = None
    try:
        sg = Sungrow(
            env("SUNGROW_APPKEY"),
            env("SUNGROW_SECRET_KEY"),
            json.loads(env("SUNGROW_TOKENS")),
            lambda v: update_secret("SUNGROW_TOKENS", v),
        )
        pv_w = sg.pv_power_w(env("SUNGROW_PLANT_ID"), env("SUNGROW_POWER_POINT", "83033"))
    except (SungrowError, OSError, ValueError, KeyError) as e:
        print(f"::warning::PV read failed: {type(e).__name__}: {e}")

    target = decide.compute_target(pv_w, now, cfg)
    action = decide.step(state, target, cfg)
    if target is not None:
        state["was_free_window"] = target.free_window

    paused_until = state.get("car_unavailable_until")
    if paused_until and datetime.fromisoformat(paused_until) > now and action.kind != "none":
        outcome = f"skipped, car paused until {datetime.fromisoformat(paused_until):%H:%M}"
    elif action.kind == "none":
        outcome = "no change"
    elif not live:
        if action.kind == "start":
            state.update(charging=True, amps=action.amps)
        elif action.kind == "stop":
            state.update(charging=False, amps=0)
        else:
            state["amps"] = action.amps
        outcome = "DRY RUN, no command sent"
    else:
        try:
            tesla = Tesla(
                env("TESLA_CLIENT_ID"),
                json.loads(env("TESLA_TOKENS")),
                env("TESLA_VIN"),
                env("TESLA_PRIVATE_KEY"),
                billing,
                lambda v: update_secret("TESLA_TOKENS", v),
            )
            state.pop("car_unavailable_until", None)
            outcome = apply_live(tesla, action, state, now)
        except (TeslaError, OSError, ValueError, KeyError) as e:
            outcome = f"car call failed: {type(e).__name__}"
            print(f"::warning::{outcome}")

    pv_txt = "n/a" if pv_w is None else f"{pv_w:.0f} W"
    tgt_txt = "unknown" if target is None else (f"charge {target.amps} A ({target.reason})" if target.charge else f"stop ({target.reason})")
    print(
        f"{now:%Y-%m-%d %H:%M} {'LIVE' if live else 'DRY'} | PV {pv_txt} | target {tgt_txt} | "
        f"action {action.kind}{' ' + str(action.amps) + ' A' if action.kind in ('start', 'set_amps') else ''} | {outcome}"
    )
    print(
        f"Fleet API this month: data {billing.get('data', 0)}, commands {billing.get('commands', 0)}, "
        f"wakes {billing.get('wakes', 0)}, approx ${cost_usd(billing):.3f}"
    )
    save_state(state)
    return 0


if __name__ == "__main__":
    sys.exit(main())
