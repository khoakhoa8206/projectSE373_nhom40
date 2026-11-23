"""W8-P1-1: checkpointer SQLite (thread_id = trip_id). Backend chết giữa chừng → continue_run chạy tiếp đúng node."""

from agent.db import repo
from agent.src.graph import app
from tests.test_uc02 import TOOLS, FakeLLM, graph_source_facts, new_trip  # noqa: F401 (fixture autouse)


class CountingLLM(FakeLLM):
    def __init__(self):
        super().__init__()
        self.calls = 0
        create = self.chat.completions.create

        def counted(**kw):
            self.calls += 1
            return create(**kw)

        self.chat.completions.create = counted


def test_crash_after_plan_continues_at_validate(db, monkeypatch):
    real_validate = app.validate

    def backend_dies(*args):
        raise KeyboardInterrupt("backend bị tắt")  # không phải Exception: giống process chết, graph không tự bắt

    trip_id = new_trip()
    monkeypatch.setattr(app, "validate", backend_dies)
    llm = CountingLLM()
    try:
        app.run_uc02(trip_id, "u-ha", client=llm, tools=TOOLS)
    except KeyboardInterrupt:
        pass
    assert llm.calls == 2  # plan đã xong (2 lượt LLM) và đã lưu checkpoint trước validate

    monkeypatch.setattr(app, "validate", real_validate)
    fresh = CountingLLM()  # "process mới": client, graph, kết nối checkpoint đều tạo lại
    res = app.continue_run(trip_id, client=fresh, tools=TOOLS)
    assert res["error"] is None and res["status"] == "validated"
    assert fresh.calls == 0  # không chạy lại plan
    nodes = [r["node"] for r in repo.query(
        "SELECT node FROM trace_events WHERE run_id = ? AND kind = 'node_start' ORDER BY seq", (res["run_id"],))]
    # validate lần 2 là lần chạy tiếp; verify (UC-11) chạy sau finalize
    assert nodes == ["load_profile", "plan", "validate", "validate", "finalize", "verify"]
    assert app.continue_run(trip_id, client=fresh, tools=TOOLS) is None  # đã tới END, không còn gì để chạy


def test_new_run_on_same_trip_starts_clean(db):
    trip_id = new_trip()
    first = app.run_uc02(trip_id, "u-ha", client=FakeLLM(), tools=TOOLS)
    second = app.run_uc02(trip_id, "u-ha", client=FakeLLM(), tools=TOOLS)
    assert first["status"] == second["status"] == "validated"
    assert first["itinerary_id"] != second["itinerary_id"]
    rounds = repo.query("SELECT planner_rounds FROM itineraries WHERE itinerary_id = ?", (second["itinerary_id"],))
    assert rounds == [{"planner_rounds": 1}]  # không kế thừa round/best của lượt trước


def test_no_checkpoint_nothing_to_continue(db):
    assert app.continue_run(new_trip(), client=FakeLLM(), tools=TOOLS) is None
