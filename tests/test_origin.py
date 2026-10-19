"""The physical-change filter."""

from custom_components.siem.core.origin import ContextLRU, is_physical


def physical(**kwargs):
    defaults = {"parent_id": None, "user_id": None, "context_id": "ctx", "caused": ContextLRU(), "now": 100.0}
    return is_physical(**{**defaults, **kwargs})


def test_a_device_report_is_physical():
    assert physical()


def test_anything_home_assistant_did_is_not():
    assert not physical(parent_id="automation-run")
    assert not physical(user_id="any-user")
    caused = ContextLRU()
    caused.add("ctx", now=100.0)
    assert not physical(caused=caused)
    assert physical(caused=caused, context_id="other")
    assert physical(caused=caused, now=161.0)


def test_lru_bounds_size_and_ttl():
    lru = ContextLRU(size=2, ttl_s=60)
    lru.add("a", 0)
    lru.add("b", 1)
    lru.add("c", 2)
    assert not lru.seen("a", 3)
    assert lru.seen("c", 3)
    assert not lru.seen("c", 63)
    assert not lru.seen(None, 3)
