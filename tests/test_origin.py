"""Origin classification for every origin."""

from custom_components.siem.core.origin import ContextLRU, Origin, classify_origin


def classify(**kwargs):
    defaults = {"parent_id": None, "user_id": None, "context_id": "ctx", "homekit_contexts": ContextLRU(), "now": 100.0}
    return classify_origin(**{**defaults, **kwargs})


def test_automation_wins_over_everything():
    assert classify(parent_id="auto", user_id="user-alice") is Origin.AUTOMATION


def test_any_user_is_a_user():
    assert classify(user_id="user-alice") is Origin.USER
    assert classify(user_id="presence-simulation-system-user") is Origin.USER


def test_automation_contexts_are_automation_but_users_still_count():
    runs = ContextLRU()
    runs.add("ctx", now=100.0)
    assert classify(automation_contexts=runs) is Origin.AUTOMATION
    assert classify(automation_contexts=runs, user_id="user-alice") is Origin.USER
    assert classify(automation_contexts=runs, context_id="other") is Origin.PHYSICAL


def test_homekit_lru_match_and_physical_fallback():
    lru = ContextLRU()
    lru.add("ctx", now=100.0)
    assert classify(context_id="ctx", homekit_contexts=lru) is Origin.HOMEKIT
    assert classify(context_id="other", homekit_contexts=lru) is Origin.PHYSICAL
    assert classify(context_id="ctx", homekit_contexts=lru, now=161.0) is Origin.PHYSICAL


def test_lru_bounds_size_and_ttl():
    lru = ContextLRU(size=2, ttl_s=60)
    lru.add("a", 0)
    lru.add("b", 1)
    lru.add("c", 2)
    assert not lru.seen("a", 3)
    assert lru.seen("c", 3)
    assert not lru.seen("c", 63)
    assert not lru.seen(None, 3)
