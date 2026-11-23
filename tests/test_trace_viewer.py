"""GET /api/runs cho trace viewer: chỉ lượt chạy của chính người dùng, lọc theo trip_id / run_id."""

import pytest
from fastapi.testclient import TestClient

from agent.db import repo
from agent.src.api.server import app


@pytest.fixture
def client(db):
    c = TestClient(app)
    assert c.post("/api/session", json={"user_id": "u-ha"}).status_code == 200
    return c


def test_runs_are_private_and_filterable(client):
    trip_a, trip_b = repo.create_trip("u-ha"), repo.create_trip("u-ha")
    run_a = repo.create_run("UC-02", trip_a, "u-ha")
    repo.create_run("UC-03", trip_b, "u-ha")
    other = repo.create_run("UC-02", repo.create_trip("u-minh"), "u-minh")

    runs = client.get("/api/runs").json()
    assert len(runs) == 2 and other not in {r["run_id"] for r in runs}
    assert [r["run_id"] for r in client.get(f"/api/runs?trip_id={trip_a}").json()] == [run_a]
    assert [r["uc"] for r in client.get(f"/api/runs?run_id={run_a}").json()] == ["UC-02"]
    assert client.get(f"/api/runs?run_id={other}").json() == []
    assert client.get(f"/api/runs/{other}/trace").status_code == 404
