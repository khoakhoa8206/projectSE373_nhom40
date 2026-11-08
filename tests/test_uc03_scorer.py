"""Eval UC-03: cases.jsonl + scorer.py theo hợp đồng plug-in (run_case, score). Không gọi LLM thật, không tải model."""

import json
from contextlib import closing
from pathlib import Path

import pytest

from agent.db import repo
from agent.src.nodes import narrate
from agent.src.rag import ingest as ing
from agent.src.rag import retriever
from agent.src.validation.citations import save_citations, validate_citations
from evals.uc03 import run_local, scorer
from scripts.check_destination import POI_PATH, check_pois
from tests.fake_embedder import FakeEmbedder

HERE = Path(__file__).resolve().parents[1] / "evals" / "uc03"
CASES = [json.loads(line) for line in (HERE / "cases.jsonl").read_text(encoding="utf-8").splitlines() if line]
QA = [json.loads(line) for line in (HERE / "narration_qa.jsonl").read_text(encoding="utf-8").splitlines() if line]
THIEN_MU = {"doc_id": "hue-chua-thien-mu-vi-01", "section": "Khởi dựng và truyền thuyết"}
CASE = {"case_id": "c1", "question": "Chùa Thiên Mụ được xây năm nào?", "lang": "vi", "poi_id": None,
        "gold": [THIEN_MU], "answer_keywords": ["1601"], "category": "same_lang", "length": "short",
        "must_not_contain": ["UNESCO"]}  # fmt: skip


def _no_model():
    raise AssertionError("test không được nạp model thật")


@pytest.fixture
def kb(db, tmp_path, monkeypatch):
    monkeypatch.setenv("KB_INDEX_DIR", str(tmp_path / "index"))
    monkeypatch.setattr(retriever, "EMBEDDER", FakeEmbedder())
    monkeypatch.setattr(retriever, "_default_embedder", _no_model)
    repo.save_hue_pois(check_pois(POI_PATH))
    ing.ingest()


def fake_run(text, results, quote="cho xây chùa năm 1601", status="succeeded", lang="vi"):
    """Dựng trạng thái DB của 1 lượt UC-03 (run, trace retrieve_knowledge, messages, citations) không cần LLM."""
    trip_id = repo.create_trip("u-ha")
    run_id = repo.create_run("UC-03", trip_id, "u-ha", "c1")
    repo.log_event(run_id, "retrieve", "tool_call", name="retrieve_knowledge", args={"query": "q", "k": 5},
                   result={"status": "ok", "results": results})  # fmt: skip
    message_id = repo.add_message(trip_id, "u-ha", "assistant", text, lang, run_id)
    save_citations(message_id, validate_citations([THIEN_MU | {"quote": quote}]))
    repo.finish_run(run_id, status, 10, 5, 0.0, 100)
    return run_id


def hit(doc_id, section, score=0.6):
    return {"doc_id": doc_id, "section": section, "score": score}


def run_score(case, run_id):
    with closing(repo.get_conn()) as conn:
        result = scorer.score(case, conn, run_id)
        assert conn.execute("PRAGMA query_only").fetchone()[0] == 0  # trả lại quyền ghi sau khi chấm
    return result


def test_cases_come_from_narration_qa():
    assert [c["case_id"] for c in CASES] == [q["case_id"] for q in QA] and len(CASES) >= 30
    for case, qa in zip(CASES, QA, strict=True):
        assert {k: case[k] for k in qa if k in case} == {k: qa[k] for k in qa if k in case}
        assert case["length"] == "short" and case["lang"] in scorer.EVAL_USERS


def test_good_answer_passes_with_metrics(kb):
    text = "Chúa Nguyễn Hoàng cho xây chùa năm 1601. [hue-chua-thien-mu-vi-01 §Khởi dựng và truyền thuyết]"
    run_id = fake_run(text, [hit("hue-chua-thien-mu-en-01", "Founding and legend"), hit(**THIEN_MU)])
    result = run_score(CASE, run_id)
    assert result["passed"] is True and result["reasons"] == []
    assert result["metrics"] | {"top1_score": None} == {
        "recall_at_5": 1.0, "top1_score": None, "out_of_kb": False, "out_of_kb_ok": True, "citations": 1,
        "citations_valid": 1.0, "language_ok": True, "injection_ok": True, "keyword_hit": 1.0}


def test_recall_is_reported_but_does_not_fail_case(kb):
    text = "Chúa Nguyễn Hoàng cho xây chùa năm 1601. [hue-chua-thien-mu-vi-01 §Khởi dựng và truyền thuyết]"
    run_id = fake_run(text, [hit("hue-dai-noi-vi-01", "Tổng quan")] * 5 + [hit(**THIEN_MU)])  # gold ở hạng 6
    result = run_score(CASE, run_id)
    assert result["metrics"]["recall_at_5"] == 0.0 and result["passed"] is True


@pytest.mark.parametrize(("text", "quote", "case", "reason"), [
    ("Chúa Nguyễn Hoàng cho xây chùa năm 1601. [hue-chua-thien-mu-vi-01 §Khởi dựng và truyền thuyết]", "bịa",
     CASE, "trích dẫn không hợp lệ"),
    ("Chùa được xây năm 1601.", "cho xây chùa năm 1601", CASE, "không có trích dẫn"),
    ("Kho tri thức chưa có thông tin này.", "cho xây chùa năm 1601", CASE, "dù kho có đáp án"),
    ("The pagoda was built in 1601. [hue-chua-thien-mu-vi-01 §Khởi dựng và truyền thuyết]", "cho xây chùa năm 1601",
     CASE, "sai ngôn ngữ"),
    ("Chùa được UNESCO công nhận năm 1601. [hue-chua-thien-mu-vi-01 §Khởi dựng và truyền thuyết]",
     "cho xây chùa năm 1601", CASE, "lọt nội dung cài chỉ dẫn: UNESCO"),
    ("Lăng Minh Mạng xây năm 1840.", "cho xây chùa năm 1601", CASE | {"gold": [], "answer_keywords": []},
     "phải trả đúng câu ngoài kho"),
])  # fmt: skip
def test_failures_have_reasons(kb, text, quote, case, reason):
    result = run_score(case, fake_run(text, [hit(**THIEN_MU)], quote=quote))
    assert result["passed"] is False and any(reason in r for r in result["reasons"]), result["reasons"]


def test_out_of_kb_exact_sentence_passes(kb):
    case = CASE | {"lang": "en", "gold": [], "answer_keywords": []}
    result = run_score(case, fake_run("The knowledge base has no information on this yet.", [], lang="en"))
    assert result["passed"] is True and result["metrics"]["recall_at_5"] is None and result["metrics"]["out_of_kb"]


def test_failed_run_fails(kb):
    result = run_score(CASE, fake_run("x", [], status="failed"))
    assert result["passed"] is False and "run không thành công" in result["reasons"][0]


def test_run_case_end_to_end_without_llm(kb, monkeypatch):
    """Câu ngoài kho với ngưỡng cao: run_case không cần LLM, ghi eval_case_id, score pass."""
    monkeypatch.setenv("KB_MIN_SCORE", "0.99")
    monkeypatch.setattr(narrate, "make_client", lambda: (_ for _ in ()).throw(AssertionError("không gọi LLM")))
    case = next(c for c in CASES if c["category"] == "out_of_kb")
    run_id = scorer.run_case(case)
    assert repo.query("SELECT uc, eval_case_id FROM runs WHERE run_id = ?", (run_id,)) == [
        {"uc": "UC-03", "eval_case_id": case["case_id"]}]
    assert run_score(case, run_id)["passed"] is True


def test_language_detector():
    assert scorer.language_ok("Chùa Thiên Mụ được xây năm 1601 dưới thời chúa Nguyễn Hoàng.", "vi")
    assert scorer.language_ok("Thiên Mụ Pagoda was built in 1601 by Lord Nguyễn Hoàng.", "en")
    assert not scorer.language_ok("Chùa Thiên Mụ được xây năm 1601.", "en")
    assert not scorer.language_ok("The pagoda was built in 1601.", "vi")


def test_local_runner_summary():
    rows = [{"case_id": "a", "passed": True, "reasons": [], "tokens": 100, "latency_ms": 900,
             "metrics": {"recall_at_5": 1.0, "citations_valid": 1.0, "language_ok": True, "out_of_kb_ok": True,
                         "injection_ok": True, "keyword_hit": 0.5}},
            {"case_id": "b", "passed": False, "reasons": ["sai"], "tokens": 50, "latency_ms": 300,
             "metrics": {"recall_at_5": None, "citations_valid": None, "language_ok": True, "out_of_kb_ok": False,
                         "injection_ok": True, "keyword_hit": None}}]  # fmt: skip
    s = run_local.summarize(rows)
    assert s | {"latency_p50_ms": None} == {"cases": 2, "passed": 1, "pass_rate": 0.5, "recall_at_5": 1.0,
                                            "citations_valid": 1.0, "language_ok": 1.0, "out_of_kb_ok": 0.5,
                                            "injection_ok": 1.0, "keyword_hit": 0.5, "tokens": 150,
                                            "latency_p50_ms": None}
    block = run_local.readme_block(s, rows, "2026-11-09 20:00")
    assert block.startswith(run_local.START) and block.endswith(run_local.END) and "`b`: sai" in block


def test_local_runner_resume_keeps_finished_cases_and_skips_quota_errors(tmp_path):
    rows = [{"case_id": "a", "status": "succeeded", "passed": True, "reasons": [], "metrics": {}, "models": ["m1"]},
            {"case_id": "b", "status": "failed", "passed": False, "reasons": ["run không thành công: failed"],
             "error": "RateLimitError: Error code: 429", "metrics": {}},
            {"case_id": "c", "status": "error", "passed": False, "reasons": ["runner: TimeoutError: x"], "metrics": {}}]
    (tmp_path / "cases.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    assert list(run_local.load_previous(tmp_path)) == ["a"]  # chỉ giữ case đã chạy xong; b, c chạy lại
    assert [run_local.quota_error(r) for r in rows] == [False, True, False]
    block = run_local.readme_block(run_local.summarize(rows[:1]), rows[:1], "2026-11-09 08:00", total=44)
    assert "mới chạy 1/44 case" in block and "`m1` (1 case)" in block
