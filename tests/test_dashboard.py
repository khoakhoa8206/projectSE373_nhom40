"""Dashboard vận hành (Buổi 11) + che PII trong trace."""

import json
from contextlib import closing

from fastapi.testclient import TestClient

from agent.db import repo
from agent.src.api import server
from agent.src.obs.dashboard import dashboard, p95
from agent.src.obs.trace import redact


def test_p95_nearest_rank():
    assert p95([]) is None
    assert p95([5]) == 5
    assert p95(range(1, 21)) == 19  # ceil(0.95 * 20) = 19
    assert p95(range(1, 101)) == 95


def _run(uc, user, status, tokens, latency, trip=None):
    run_id = repo.create_run(uc, trip, user)
    repo.finish_run(run_id, status, tokens, 0, 0.01, latency)
    return run_id


def test_dashboard_counts_only_own_runs(db):
    me = repo.create_user("A", user_id="u-a")
    other = repo.create_user("B", user_id="u-b")
    trip = repo.create_trip(me)
    ok = _run("UC-02", me, "succeeded", 1000, 2000, trip)
    _run("UC-02", me, "failed", 3000, 4000, trip)
    _run("UC-02", me, "interrupted", 0, 100, trip)
    _run("UC-03", other, "succeeded", 9999, 9999)  # của người khác: không được đếm
    repo.log_event(ok, "plan", "tool_call", name="get_poi", args={"poi_id": "x"}, result={})
    repo.log_event(ok, "plan", "tool_call", name="get_poi", error="KeyError: x")
    repo.log_event(ok, "plan", "tool_call", name="search_poi", result=[])
    repo.log_event(ok, "plan", "guardrail", name="tool_denied")
    repo.query("INSERT INTO approvals (approval_id, trip_id, run_id, kind, payload, created_at)"
               " VALUES ('ap-1', ?, ?, 'itinerary_approval', '{}', ?)", (trip, ok, repo.now()))  # fmt: skip

    with closing(repo.get_conn()) as conn:
        d = dashboard([conn], me)

    t = d["total"]
    assert (t["runs"], t["succeeded"], t["failed"], t["interrupted"]) == (3, 1, 1, 1)
    assert t["success_rate"] == 0.5  # interrupted không tính là lỗi
    assert t["avg_tokens"] == 2000 and t["max_tokens"] == 3000  # lượt 0 token (chưa gọi LLM) không kéo trung bình
    assert t["latency_p95_ms"] == 4000
    assert list(d["by_uc"]) == ["UC-02"]
    assert d["tools"][0] == {"name": "get_poi", "calls": 2, "errors": 1, "error_rate": 0.5}
    assert d["guardrails"] == {"tool_denied": 1}
    assert d["approvals"] == {"pending": 1, "by_kind": {"itinerary_approval:pending": 1}}


def test_dashboard_api_requires_login_and_scopes_user(db):
    from agent.db.init import FICTIONAL_USERS

    user = FICTIONAL_USERS[0][0]
    _run("UC-03", user, "succeeded", 10, 10)
    _run("UC-03", FICTIONAL_USERS[1][0], "succeeded", 10, 10)
    client = TestClient(server.app)
    assert client.get("/api/dashboard").status_code == 401
    client.post("/api/session", json={"user_id": user}).raise_for_status()
    assert client.get("/api/dashboard").json()["total"]["runs"] == 1


def test_redact_email_phone_in_trace(db):
    assert redact({"q": "mail a.b@gm.uit.edu.vn, gọi 0901234567 hoặc +84901234567", "n": [5, "02343822355"]}) == {
        "q": "mail [email], gọi [phone] hoặc [phone]",
        "n": [5, "[phone]"],
    }
    assert (
        redact("vé 150000 đồng ngày 2026-11-25, POI hue-dai-noi") == "vé 150000 đồng ngày 2026-11-25, POI hue-dai-noi"
    )
    run_id = _run("UC-01", None, "succeeded", 0, 0)
    repo.log_event(run_id, "intake", "tool_call", args={"text": "email tôi: x@y.com"}, error="sai 0912345678")
    row = repo.query("SELECT args, error FROM trace_events WHERE run_id = ?", (run_id,))[0]
    assert json.loads(row["args"]) == {"text": "email tôi: [email]"} and row["error"] == "sai [phone]"
