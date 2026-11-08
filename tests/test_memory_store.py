"""W8-P1-3: memory store theo user_id (UC-07 v0)."""

import pytest

from agent.db import repo
from agent.src.memory import store


def test_users_never_see_each_other(db):
    mid = store.memory_write("u-ha", "interest", "lịch sử")
    store.memory_write("u-minh", "pace", "relaxed")
    assert [m["value"] for m in store.memory_read("u-ha")] == ["lịch sử"]
    assert not store.memory_update("u-minh", mid, "đổi trộm")  # sửa/xoá mục của người khác: không có tác dụng
    assert not store.memory_delete("u-minh", mid)
    assert store.memory_read("u-ha")[0]["value"] == "lịch sử"


def test_sensitive_needs_consent_and_revoke_deletes(db):
    with pytest.raises(store.MemoryRuleError):
        store.memory_write("u-ha", "allergy", "dị ứng đậu phộng", "sensitive")
    store.grant_sensitive_consent("u-ha")
    store.memory_write("u-ha", "allergy", "dị ứng đậu phộng", "sensitive")
    store.memory_write("u-ha", "interest", "ẩm thực")
    store.revoke_sensitive_consent("u-ha")
    assert [m["kind"] for m in store.memory_read("u-ha")] == ["interest"]
    with pytest.raises(store.MemoryRuleError):
        store.memory_write("u-ha", "allergy", "dị ứng tôm", "sensitive")  # đã thu hồi thì phải đồng ý lại


def test_guardrails_and_dedupe(db):
    for kind, value in [("other", "ở 16.4698, 107.5786"), ("visited_city", "Kiệt 12 Lê Lợi"), ("nope", "x"),
                        ("interest", "")]:
        with pytest.raises(store.MemoryRuleError):
            store.memory_write("u-ha", kind, value)
    a = store.memory_write("u-ha", "visited_city", "Huế")
    assert store.memory_write("u-ha", "visited_city", "Huế") == a and len(store.memory_read("u-ha")) == 1


def test_expired_items_are_hidden_and_purged(db):
    mid = store.memory_write("u-ha", "pace", "relaxed")
    repo.query("UPDATE memory_items SET expires_at = '2000-01-01T00:00:00+07:00' WHERE memory_id = ?", (mid,))
    assert store.memory_read("u-ha") == []
    assert repo.query("SELECT 1 FROM memory_items WHERE memory_id = ?", (mid,)) == []


def test_delete_is_soft_and_update_validates(db):
    mid = store.memory_write("u-ha", "food_dislike", "không ăn cay")
    with pytest.raises(store.MemoryRuleError):
        store.memory_update("u-ha", mid, "16.46981,107.57863")
    assert store.memory_update("u-ha", mid, "không ăn quá cay")
    assert store.memory_delete("u-ha", mid) and store.memory_read("u-ha") == []
    assert repo.query("SELECT deleted_at IS NOT NULL AS gone FROM memory_items WHERE memory_id = ?", (mid,)) == [{"gone": 1}]
