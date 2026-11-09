"""W8-P1-4: SSE sự kiện node (GET /api/runs/{run_id}/stream), chạy nền ?background=true, toạ độ đã che."""

import json

import pytest
from fastapi.testclient import TestClient

from agent.db import repo
from agent.src.api import server, stream
from agent.src.graph import app
from tests.test_uc02 import PROFILE, TOOLS, FakeLLM, graph_source_facts  # noqa: F401 (fixture autouse)


def read_sse(client, run_id):
    events = []
    with client.stream("GET", f"/api/runs/{run_id}/stream") as res:
        assert res.status_code == 200 and res.headers["content-type"].startswith("text/event-stream")
        event = None
        for line in res.iter_lines():
            if line.startswith("event: "):
                event = line[7:]
            elif line.startswith("data: "):
                events.append((event, json.loads(line[6:])))
    return events


@pytest.fixture
def client(db, monkeypatch):
    monkeypatch.setattr(app, "make_client", FakeLLM)
    monkeypatch.setattr(app, "default_tools", lambda: TOOLS)
    monkeypatch.setattr(stream, "POLL_S", 0.01)
    c = TestClient(server.app)
    c.post("/api/session", json={"user_id": "u-ha"})
    return c


def test_background_plan_streams_nodes_then_interrupt_then_done(client):
    trip_id = client.post("/api/trips", json=PROFILE).json()["trip_id"]
    started = client.post(f"/api/trips/{trip_id}/plan?background=true").json()
    assert started["status"] == "running"

    events = read_sse(client, started["run_id"])
    kinds = [e for e, _ in events]
    assert kinds[0] == "node_start" and events[0][1]["node"] == "load_profile"
    assert {"llm_call", "tool_call", "node_end", "approval"} <= set(kinds)
    assert kinds[-2:] == ["interrupt", "done"]
    assert events[-2][1]["kind"] == "itinerary_approval" and events[-1][1]["status"] == "interrupted"
    seqs = [d["seq"] for e, d in events if "seq" in d]
    assert seqs == sorted(seqs) and len(seqs) == len(set(seqs))  # đủ, đúng thứ tự, không lặp

    body = {"approval_id": events[-2][1]["approval_id"], "decision": "approved"}
    assert client.post(f"/api/trips/{trip_id}/resume?background=true", json=body).json()["run_id"] == started["run_id"]
    tail = read_sse(client, started["run_id"])  # stream lại cùng run: phát lại trace, giờ dừng ở bước lưu bộ nhớ
    assert tail[-2][0] == "interrupt" and tail[-2][1]["kind"] == "memory_save"
    assert tail[-1] == ("done", {"run_id": started["run_id"], "status": "interrupted"})
    assert client.post(f"/api/trips/{trip_id}/resume?background=true", json=body).status_code == 409


def test_stream_masks_coordinates_and_checks_owner(client):
    trip_id = client.post("/api/trips", json=PROFILE).json()["trip_id"]
    run_id = repo.create_run("UC-02", trip_id, "u-ha")
    repo.log_event(run_id, "plan", "tool_call", name="get_poi", result={"lat": 16.469812, "lon": 107.578634})
    repo.finish_run(run_id, "succeeded", 0, 0, 0.0, 1)
    events = read_sse(client, run_id)
    assert events[0][1]["result"] == {"lat": 16.47, "lon": 107.58}
    assert events[-1] == ("done", {"run_id": run_id, "status": "succeeded"})

    other = TestClient(server.app)
    other.post("/api/session", json={"user_id": "u-minh"})
    assert other.get(f"/api/runs/{run_id}/stream").status_code == 404
