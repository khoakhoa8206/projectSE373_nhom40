import json

from scripts.export_trace import export


def test_export_masks_coords_from_jsonl_file(tmp_path):
    src = tmp_path / "results" / "all-x" / "uc11" / "traces" / "r-1.jsonl"
    src.parent.mkdir(parents=True)
    src.write_text(json.dumps({"seq": 1, "result": {"lat": 16.469812, "geometry": {"coordinates": [107.578612, 16.469812]}}}) + "\n",
                   encoding="utf-8")  # fmt: skip
    out, n = export("r-1", "UC-11", out_root=tmp_path / "samples", roots=(tmp_path / "results",))
    assert (n, out.parent.name) == (1, "uc-11")
    ev = json.loads(out.read_text(encoding="utf-8"))
    assert ev["result"] == {"lat": 16.47, "geometry": {"coordinates": [107.58, 16.47]}}


def test_export_falls_back_to_db(db):
    from agent.db import repo

    run_id = repo.create_run("UC-11", repo.create_trip("u-ha"), "u-ha")
    repo.log_event(run_id, "verify", "guardrail", args={"lon": 107.578612})
    out, n = export(run_id, "UC-11", out_root=db / "samples", roots=(db / "none",))  # không đọc file, chỉ DB
    assert n == 1 and json.loads(out.read_text(encoding="utf-8"))["args"] == {"lon": 107.58}
