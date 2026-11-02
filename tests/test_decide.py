import unittest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from controller.decide import Config, compute_target, step

TZ = ZoneInfo("Australia/Brisbane")
CFG = Config()


def at(h, m=0):
    return datetime(2026, 11, 2, h, m, tzinfo=TZ)


def run(state, pv, now):
    t = compute_target(pv, now, CFG)
    a = step(state, t, CFG)
    if t is not None:
        state["was_free_window"] = t.free_window
    if a.kind == "start":
        state.update(charging=True, amps=a.amps)
    elif a.kind == "stop":
        state.update(charging=False, amps=0)
    elif a.kind == "set_amps":
        state["amps"] = a.amps
    return a


class TargetTests(unittest.TestCase):
    def test_free_window_full_amps_without_solar(self):
        t = compute_target(0, at(11), CFG)
        self.assertEqual((t.charge, t.amps), (True, 10))

    def test_window_end_exclusive(self):
        self.assertFalse(compute_target(0, at(15), CFG).charge)

    def test_surplus_amps(self):
        # 3000 W - 1000 W = 2000 W / 230 V = 8.69 -> 8 A
        self.assertEqual(compute_target(3000, at(9), CFG).amps, 8)

    def test_cap_at_max(self):
        self.assertEqual(compute_target(5000, at(9), CFG).amps, 10)

    def test_below_minimum_stops(self):
        # 2000 W - 1000 W = 1000 W / 230 = 4 A < 5 A
        self.assertFalse(compute_target(2000, at(9), CFG).charge)

    def test_unknown_pv_outside_window(self):
        self.assertIsNone(compute_target(None, at(9), CFG))

    def test_night_does_nothing(self):
        s = {}
        self.assertEqual(run(s, 0, at(22)).kind, "none")
        self.assertEqual(run(s, 0, at(22, 5)).kind, "none")


class HysteresisTests(unittest.TestCase):
    def test_start_needs_two_readings(self):
        s = {}
        self.assertEqual(run(s, 3000, at(9)).kind, "none")
        a = run(s, 3000, at(9, 5))
        self.assertEqual((a.kind, a.amps), ("start", 8))

    def test_cloud_blip_does_not_stop(self):
        s = {"charging": True, "amps": 8}
        self.assertEqual(run(s, 500, at(9)).kind, "none")
        self.assertEqual(run(s, 3000, at(9, 5)).kind, "none")
        self.assertTrue(s["charging"])

    def test_sustained_drop_stops(self):
        s = {"charging": True, "amps": 8}
        run(s, 500, at(9))
        self.assertEqual(run(s, 500, at(9, 5)).kind, "stop")

    def test_amps_follow_surplus_when_charging(self):
        s = {"charging": True, "amps": 8}
        a = run(s, 2600, at(9))
        self.assertEqual((a.kind, a.amps), ("set_amps", 6))

    def test_no_repeat_command_when_already_right(self):
        s = {"charging": True, "amps": 8}
        self.assertEqual(run(s, 3000, at(9)).kind, "none")

    def test_free_window_starts_immediately_at_11(self):
        s = {}
        run(s, 0, at(10, 55))
        a = run(s, 0, at(11))
        self.assertEqual((a.kind, a.amps), ("start", 10))

    def test_free_window_stops_immediately_at_15_without_surplus(self):
        s = {}
        run(s, 0, at(11))
        self.assertEqual(run(s, 0, at(15)).kind, "stop")

    def test_free_window_end_with_surplus_adjusts_amps(self):
        s = {}
        run(s, 0, at(11))
        a = run(s, 3000, at(15))
        self.assertEqual((a.kind, a.amps), ("set_amps", 8))

    def test_max_one_start_stop_per_10_minutes_under_flapping_cloud(self):
        s = {}
        changes = 0
        for i, pv in enumerate([3000, 500] * 12):
            if run(s, pv, at(7) + timedelta(minutes=5 * i)).kind in ("start", "stop"):
                changes += 1
        self.assertEqual(changes, 0)


if __name__ == "__main__":
    unittest.main()
