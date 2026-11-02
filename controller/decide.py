"""Pure decision logic. No I/O, so it can be unit tested."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, time


@dataclass(frozen=True)
class Config:
    house_load_w: float = 1000.0
    volts: float = 230.0
    max_amps: int = 10
    min_amps: int = 5
    free_start: time = time(11, 0)
    free_end: time = time(15, 0)
    confirm_readings: int = 2


@dataclass(frozen=True)
class Target:
    charge: bool
    amps: int
    reason: str
    free_window: bool


def in_free_window(now: datetime, cfg: Config) -> bool:
    return cfg.free_start <= now.time() < cfg.free_end


def compute_target(pv_w: float | None, now: datetime, cfg: Config) -> Target | None:
    """Return the desired charging state, or None if it cannot be determined."""
    if in_free_window(now, cfg):
        return Target(True, cfg.max_amps, "free window", True)
    if pv_w is None:
        return None
    surplus = pv_w - cfg.house_load_w
    amps = min(cfg.max_amps, math.floor(surplus / cfg.volts)) if surplus > 0 else 0
    if amps < cfg.min_amps:
        return Target(False, 0, f"surplus {surplus:.0f} W below {cfg.min_amps} A", False)
    return Target(True, amps, f"surplus {surplus:.0f} W", False)


@dataclass(frozen=True)
class Action:
    kind: str  # "none", "start", "stop", "set_amps"
    amps: int = 0


def step(state: dict, target: Target | None, cfg: Config) -> Action:
    """Apply hysteresis and decide what to send. Mutates state['pending'].

    state keys used: charging (bool), amps (int), pending ({"charge": bool, "count": int} | None).
    The believed charging state is only updated by the caller after a command succeeds.
    """
    if target is None:
        return Action("none")
    believed = bool(state.get("charging", False))

    if target.charge == believed:
        state["pending"] = None
        if believed and state.get("amps") != target.amps:
            return Action("set_amps", target.amps)
        return Action("none")

    # Free-window transitions are clock driven, not cloud driven: act immediately.
    if target.free_window or state.get("was_free_window"):
        state["pending"] = None
        return Action("start", target.amps) if target.charge else Action("stop")

    pending = state.get("pending")
    if pending and pending.get("charge") == target.charge:
        pending["count"] += 1
    else:
        pending = {"charge": target.charge, "count": 1}
    state["pending"] = pending
    if pending["count"] < cfg.confirm_readings:
        return Action("none")
    state["pending"] = None
    return Action("start", target.amps) if target.charge else Action("stop")
