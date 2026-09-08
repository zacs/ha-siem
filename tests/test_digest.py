"""Digest window computation across multiple times and a restart."""

from datetime import datetime, timedelta, timezone

import pytest

from custom_components.siem.core.digest import fallback_text, is_due, parse_times, scheduled_between, summarize_window

TZ = timezone(timedelta(hours=-5))


def at(day, hour, minute=0):
    return datetime(2026, 9, day, hour, minute, tzinfo=TZ)


def test_parse_times_validates():
    assert parse_times(["08:00", "20:30", "08:00"]) == [datetime(2000, 1, 1, 8).time(), datetime(2000, 1, 1, 20, 30).time()]
    with pytest.raises(ValueError):
        parse_times(["8pm"])


def test_due_across_multiple_times():
    times = ["08:00", "20:00"]
    assert not is_due(times, at(1, 7), at(1, 7, 59))
    assert is_due(times, at(1, 7), at(1, 8))
    assert not is_due(times, at(1, 8), at(1, 19, 59))
    assert is_due(times, at(1, 8), at(1, 20))


def test_restart_catches_up_the_missed_window():
    times = ["08:00", "20:00"]
    last_run = at(1, 20)
    # Home Assistant was down from 07:00 to 09:30 the next day.
    assert scheduled_between(times, last_run, at(2, 9, 30)) == [at(2, 8)]
    assert is_due(times, last_run, at(2, 9, 30))
    # Two days down: both missed slots are listed, the caller posts one digest.
    assert len(scheduled_between(times, last_run, at(3, 9))) == 3


def test_no_last_run_means_not_due():
    assert not is_due(["08:00"], None, at(1, 8))
    assert scheduled_between([], at(1, 7), at(1, 9)) == []


def test_summary_and_fallback():
    incidents = [
        {"id": "a", "started": at(1, 9).timestamp(), "peak_tier": "verify", "labels": ["thats_me"]},
        {"id": "b", "started": at(1, 21).timestamp(), "peak_tier": "deter"},
        {"id": "old", "started": at(1, 5).timestamp(), "peak_tier": "alarm"},
    ]
    changes = [{"at": at(1, 10).timestamp(), "rule": "light_physical", "old": 1.0, "new": 0.9}]
    summary = summarize_window(incidents, changes, at(1, 8), at(2, 8))
    assert summary["incident_count"] == 2
    assert summary["labels"] == {"a": ["thats_me"]}
    assert summary["weight_changes"] == changes
    assert fallback_text(summary) == "2 incidents (1 deter, 1 verify), 1 weight changes"
    assert fallback_text(summarize_window([], [], None, at(2, 8))).startswith("0 incidents (no incidents)")
