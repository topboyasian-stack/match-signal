"""Focused regression checks for the eFootball recent O/U spoiler guard."""

from odds_builder import _efootball_recent_spoiler_guard


def rows(flags):
    return [{"win": bool(flag)} for flag in flags]


# Scope: non-eFootball products are untouched.
ok, details = _efootball_recent_spoiler_guard("vfootball", rows([False] * 20))
assert ok and details["enabled"] is False

# A four-loss live streak is quarantined even when older history was strong.
flags = [False, False, False, False] + [True] * 16
ok, details = _efootball_recent_spoiler_guard("efootball_gt", rows(flags))
assert not ok
assert details["reason"] == "efootball_recent_loss_streak"

# A fresh last-10 collapse is quarantined before stale wins can rescue the key.
flags = [True, True, True, True] + [False] * 6 + [True] * 10
ok, details = _efootball_recent_spoiler_guard("efootball_gt", rows(flags))
assert not ok
assert details["reason"] == "efootball_recent_last10_below_threshold"

# A weaker last-20 history is also quarantined when the last-10 window alone
# does not cross the kill switch.
flags = [True] * 6 + [False] * 14
ok, details = _efootball_recent_spoiler_guard("efootball_gt", rows(flags))
assert not ok
assert details["reason"] == "efootball_recent_last20_below_threshold"

# Exactly 50% in the latest 10 is allowed by the strict '< 50%' rule.
flags = [True] * 5 + [False] * 5 + [True] * 10
ok, details = _efootball_recent_spoiler_guard("efootball_gt", rows(flags))
assert ok
assert details["status"] == "passed"

# Fewer than 12 exact-side observations does not trigger the new guard.
flags = [True] * 8 + [False] * 4
ok, details = _efootball_recent_spoiler_guard("efootball_gt", rows(flags))
assert ok
assert details["status"] == "not_triggered_insufficient_recent_sample"

print("eFootball recent spoiler guard regression checks: PASS")
