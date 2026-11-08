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


def test_memory_api_is_scoped_to_session_user(db):
    from fastapi.testclient import TestClient

    from agent.src.api import server

    mid = store.memory_write("u-ha", "interest", "lịch sử")
    store.grant_sensitive_consent("u-ha")
    store.memory_write("u-ha", "allergy", "dị ứng tôm", "sensitive")
    ha, minh = TestClient(server.app), TestClient(server.app)
    ha.post("/api/session", json={"user_id": "u-ha"})
    minh.post("/api/session", json={"user_id": "u-minh"})
    assert TestClient(server.app).get("/api/memory").status_code == 401
    assert minh.get("/api/memory").json() == {"items": [], "sensitive_consent": False}
    assert minh.patch(f"/api/memory/{mid}", json={"value": "x"}).status_code == 404
    assert minh.delete(f"/api/memory/{mid}").status_code == 404

    assert ha.patch(f"/api/memory/{mid}", json={"value": "16.46981, 107.57863"}).status_code == 422
    got = ha.patch(f"/api/memory/{mid}", json={"value": "lịch sử triều Nguyễn"}).json()
    assert {m["value"] for m in got["items"]} == {"lịch sử triều Nguyễn", "dị ứng tôm"} and got["sensitive_consent"]
    got = ha.post("/api/memory/consent/revoke").json()
    assert [m["kind"] for m in got["items"]] == ["interest"] and not got["sensitive_consent"]
    assert ha.delete(f"/api/memory/{mid}").json()["items"] == []
