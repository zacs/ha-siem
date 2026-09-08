"""Origin classification for every origin."""

from custom_components.siem.core.origin import ContextLRU, Origin, UserInfo, classify_origin, default_trusted_user_ids

TRUSTED = ["user-alice", "user-presence"]


def classify(**kwargs):
    defaults = {"parent_id": None, "user_id": None, "context_id": "ctx", "trusted_user_ids": TRUSTED, "homekit_contexts": ContextLRU(), "now": 100.0}
    return classify_origin(**{**defaults, **kwargs})


def test_automation_wins_over_everything():
    assert classify(parent_id="auto", user_id="user-alice") is Origin.AUTOMATION


def test_trusted_and_untrusted_users():
    assert classify(user_id="user-alice") is Origin.USER_TRUSTED
    assert classify(user_id="user-presence") is Origin.USER_TRUSTED
    assert classify(user_id="user-mallory") is Origin.USER_UNTRUSTED


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


def test_presence_simulation_user_is_trusted_by_default():
    users = [UserInfo("u1", "Alice"), UserInfo("u9", "presence simulation", system_generated=True)]
    trusted = default_trusted_user_ids(["u1", None], users)
    assert trusted == ["u1", "u9"]
    lru = ContextLRU()
    assert classify_origin(parent_id=None, user_id="u9", context_id="c", trusted_user_ids=trusted, homekit_contexts=lru, now=0) is Origin.USER_TRUSTED
