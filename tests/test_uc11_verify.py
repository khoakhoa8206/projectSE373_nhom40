"""UC-11 verify v0: normalize, decide, tách claim (regex + LLM giả), đối chiếu tool, sửa bằng code, cổng chặn,
claim từ lịch trình có cấu trúc. Giờ, giá, quãng đường trong các test dùng fixture `db` là dữ liệu TEST hư cấu;
test_sample_itineraries chạy trên dữ liệu Huế thật."""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from agent.db import repo
from agent.db.init import init_db
from agent.schemas import Claim, Itinerary, TripProfile
from agent.src.nodes import verify
from agent.src.nodes.verify import DraftClaim, Evidence, LlmClaim, LlmClaims, decide, normalize, verify_itinerary
from agent.src.tools import weather
from mocks.mock_weather import app as mock
from scripts import load_destination

FIXTURES = Path(__file__).resolve().parents[1] / "evals" / "fixtures" / "itineraries"

CTX = {"destination_id": "hue", "trip_dates": ["2026-11-27", "2026-11-27"], "lang": "vi"}


@pytest.mark.parametrize("raw, kind, expect", [
    ("7h30", "time", "07:30"), ("7:30 sáng", "time", "07:30"), ("7.30am", "time", "07:30"),
    ("5 rưỡi chiều", "time", "17:30"), ("17h", "time", "17:00"), ("5pm", "time", "17:00"), ("17", "time", None),
    ("150k", "money", 150000), ("150 nghìn", "money", 150000), ("150.000đ", "money", 150000),
    ("VND 150,000", "money", 150000), ("1,5 triệu", "money", 1500000),
    ("5/6/2026", "date", "2026-06-05"), ("June 5th 2026", "date", "2026-06-05"),
    ("mùng 5 tháng 6 năm 2026", "date", "2026-06-05"), ("tháng 6/2026", "date", "2026-06"), ("31/2/2026", "date", None),
    ("1,5 km", "distance", 1500), ("1500 m", "distance", 1500), ("26,4 °C", "temp", 26.4), ("3 mm", "mm", 3.0),
])  # fmt: skip
def test_normalize(raw, kind, expect):
    assert normalize(raw, kind) == expect


def test_normalize_date_uses_trip_year():
    assert normalize("27/11", "date", 2026) == "2026-11-27"
    assert normalize("27/11", "date") is None  # không đoán năm


def claim(attribute="adult_price", value=150000, **kw):
    return DraftClaim(claim_type="price", claim_text="x", start=0, sentence=0, attribute=attribute, value_raw="x",
                      value_norm=value, **kw)  # fmt: skip


def ev(value, kind="tool", anomalous=False):
    return Evidence(value_norm=value, kind=kind, ref="r", source_url="https://example.org", anomalous=anomalous)


@pytest.mark.parametrize("c, evidences, expect", [
    (claim(issue="entity_not_found"), [ev(150000)], ("unverified", "entity_not_found")),
    (claim(value=None), [ev(150000)], ("unverified", "unsupported_format")),
    (claim(), [], ("unverified", "no_source")),
    (claim("temp_max_c", 48.0), [ev(48.0, anomalous=True)], ("unverified", "weather_anomalous")),
    (claim(), [ev(150000)], ("verified", "match")),
    (claim(), [ev(200000)], ("contradicted", "mismatch")),
    (claim(), [ev(150000, "kb"), ev(200000, "kb")], ("unverified", "sources_disagree")),
    (claim(), [ev(200000), ev(150000, "kb")], ("contradicted", "sources_disagree")),  # tool thắng kb
    (claim("temp_max_c", 27.0), [ev(26.4)], ("verified", "match")),  # ±2 °C
    (claim("precip_mm", 10.0), [ev(3.0)], ("contradicted", "mismatch")),  # lệch > 5 mm
    (claim("travel_minutes", 9), [ev(8)], ("verified", "match")),  # ±20 %
])  # fmt: skip
def test_decide(c, evidences, expect):
    assert decide(c, evidences)[:2] == expect


@pytest.fixture
def run_id(db, monkeypatch):
    repo.query("UPDATE pois SET ticket_price_vnd = 200000, opening_hours = 'Mo-Su 08:00-17:00' WHERE poi_id = 'hue-dai-noi'")
    repo.query("""INSERT INTO travel_matrix VALUES ('hue-dai-noi', 'hue-cho-dong-ba', 'drive', 8, 2500, 'osrm', '2026-10-24'),
                                                  ('hue-dai-noi', 'hue-cho-dong-ba', 'walk', 30, 2300, 'osrm', '2026-10-24')""")
    monkeypatch.setattr(weather, "_client", lambda: TestClient(mock.app, base_url="http://localhost:8081",
                                                               headers={"X-Mock-Mode": "normal"}))  # fmt: skip
    return repo.create_run("UC-11", repo.create_trip("u-ha"), "u-ha")


def check(text, run_id):
    """Như node chạy trên văn bản, nhưng tách claim bằng regex: tất định, không cần key LLM."""
    return verify.verify_and_fix(text, run_id, ctx=CTX, extractor=verify.extract_regex)


def stored(run_id):
    return {r["claim_text"]: dict(r) for r in repo.query("SELECT * FROM claims WHERE run_id = ?", (run_id,))}


def test_wrong_hours_and_price_are_corrected(run_id):
    res = check("Đại Nội mở cửa 8h–17h30, vé người lớn 150.000đ.", run_id)
    assert res["text"] == "Đại Nội mở cửa 8h–17:00, vé người lớn 200.000đ." and not res["blocked"]
    rows = stored(run_id)
    assert rows["8h"]["status"] == "verified" and rows["8h"]["source_url"] == "https://example.org"
    assert rows["17h30"]["status"] == "contradicted" and rows["17h30"]["corrected_text"] == "17:00"
    assert rows["150.000đ"].items() >= {"status": "contradicted", "corrected_text": "200.000đ", "evidence_ref": "hue-dai-noi"}.items()


def test_missing_data_is_labeled_not_guessed(run_id):
    # Chợ Đông Ba không có giá/giờ trong dữ liệu test → chưa xác minh, không đoán
    res = check("Chợ Đông Ba vé 50.000đ. Chùa Ông mở cửa 7h.", run_id)
    assert res["text"] == "Chợ Đông Ba vé 50.000đ (chưa xác minh). Chùa Ông mở cửa 7h (chưa xác minh)."
    rows = stored(run_id)
    assert rows["50.000đ"]["status"] == rows["7h"]["status"] == "unverified"


def test_closed_day_contradicted(run_id):
    res = check("Đại Nội đóng cửa thứ Hai.", run_id)  # dữ liệu test: mở cả tuần
    assert res["text"] == "Đại Nội mở cửa thứ Hai."


def test_weather_and_travel(run_id):
    # mock normal ngày 27/11: 21.1–26.4 °C, 2.6 mm · ma trận test: đi xe 8 phút, 2,5 km
    text = "Ngày 27/11 cao nhất 26 °C, mưa 3 mm. Từ Đại Nội đi xe tới Chợ Đông Ba mất 20 phút, khoảng 2,5 km."
    res = check(text, run_id)
    assert res["text"] == text.replace("20 phút", "8 phút")
    rows = stored(run_id)
    assert {rows[k]["status"] for k in ("26 °C", "3 mm", "2,5 km")} == {"verified"}
    assert rows["26 °C"]["evidence_ref"] == str(repo.weather_for_run(run_id)["2026-11-27"]["snapshot_id"])


def test_abnormal_weather_never_verified(run_id, monkeypatch):
    monkeypatch.setattr(weather, "_client", lambda: TestClient(mock.app, base_url="http://localhost:8081",
                                                               headers={"X-Mock-Mode": "abnormal"}))  # fmt: skip
    res = check("Ngày 27/11 Huế nóng 48 °C.", run_id)  # case tấn công số 5
    assert stored(run_id)["48 °C"]["status"] == "unverified" and "chưa xác minh" in res["text"]


def test_not_facts_are_ignored(run_id):
    text = "Ngân sách 8 triệu, xuất phát lúc 7h, tham quan 90 phút."
    assert check(text, run_id) == {"text": text, "claims": [], "blocked": False}


def test_gate_blocks_when_correction_still_wrong(run_id, monkeypatch):
    monkeypatch.setattr(verify, "corrected_text", lambda c, e, lang="vi": "180.000đ")  # giả lập bug ở bước sửa
    res = check("Vé Đại Nội 150.000đ.", run_id)
    assert res["blocked"] and res["text"] == verify.SAFE_FALLBACK["vi"]
    assert "150.000đ" not in res["text"] and "180.000đ" not in res["text"]


def test_festival_date_unverified_not_guessed(run_id):
    res = check("Festival Huế 2026 khai mạc 5/6/2026.", run_id)  # chưa có nguồn RAG của P3
    assert stored(run_id)["5/6/2026"]["status"] == "unverified" and "(chưa xác minh)" in res["text"]


def test_claim_model_repeats_schema_checks():
    base = {"run_id": "r", "target_type": "message", "target_id": "x", "claim_type": "price", "claim_text": "150k"}
    with pytest.raises(ValidationError, match="source_url"):
        Claim(**base, status="verified")
    with pytest.raises(ValidationError, match="corrected_text"):
        Claim(**base, status="contradicted")
    assert Claim(**base, status="unverified").status == "unverified"


def fake_llm(monkeypatch, claims):
    calls = []

    def loop(client, system, user, tools, output, run_id, node, usage, max_turns):
        calls.append(user)
        return LlmClaims(claims=claims)

    monkeypatch.setattr(verify, "agent_loop", loop)
    monkeypatch.setattr(verify, "make_client", lambda: None)
    return calls


def test_llm_extraction_checked_by_code(run_id, monkeypatch):
    # LLM bắt được cách viết tự nhiên mà regex không đọc là giờ đóng cửa ("tới tận 5 rưỡi chiều");
    # LLM gán bừa POI không có trong văn bản thì code bỏ (không đoán POI); LLM chép đoạn không có trong văn bản thì bỏ.
    calls = fake_llm(monkeypatch, [
        LlmClaim(claim_type="opening_hours", attribute="close_time", claim_text="mở tới tận 5 rưỡi chiều",
                 value="5 rưỡi chiều", poi_id="hue-dai-noi"),
        LlmClaim(claim_type="price", attribute="adult_price", claim_text="80.000đ", value="80.000đ",
                 poi_id="hue-cho-dong-ba"),
        LlmClaim(claim_type="price", attribute="adult_price", claim_text="999đ", value="999đ", poi_id="hue-dai-noi"),
    ])  # fmt: skip
    text = "Đại Nội mở tới tận 5 rưỡi chiều. Vé chợ đêm 80.000đ."
    claims = verify.verify_text(text, run_id, "m-1", ctx=CTX)
    assert "Đại Nội" in calls[0] and "Chợ Đông Ba" not in calls[0]  # chỉ đưa LLM các điểm có tên trong văn bản
    got = {c.claim_text: c for c in claims}
    assert got["5 rưỡi chiều"].status == "contradicted" and got["5 rưỡi chiều"].corrected_text == "17:00"
    assert got["80.000đ"].status == "unverified"  # poi_id bị bỏ vì "Chợ Đông Ba" không có trong văn bản
    assert "999đ" not in got and all(isinstance(c, Claim) and c.claim_id for c in claims)


def test_llm_failure_falls_back_to_regex(run_id, monkeypatch):
    def broken(*a, **k):
        raise RuntimeError("không có LLM_API_KEY")

    monkeypatch.setattr(verify, "agent_loop", broken)
    monkeypatch.setattr(verify, "make_client", lambda: None)
    claims = verify.verify_text("Vé Đại Nội 150.000đ.", run_id, ctx=CTX)
    assert [(c.claim_text, c.status) for c in claims] == [("150.000đ", "contradicted")]
    assert repo.query("SELECT name FROM trace_events WHERE run_id = ? AND name = 'llm_extract_failed'", (run_id,))


def test_no_digits_skips_llm(run_id, monkeypatch):
    calls = fake_llm(monkeypatch, [])
    assert verify.verify_text("Đại Nội rất đẹp, nên đi buổi sáng.", run_id, ctx=CTX) == [] and calls == []


@pytest.mark.parametrize("name", sorted(p.name for p in FIXTURES.glob("*.json")))
def test_sample_itineraries(tmp_path, monkeypatch, name):
    """verify_itinerary chạy độc lập (chưa ghép graph) trên lịch trình mẫu + dữ liệu Huế thật + mock-weather."""
    monkeypatch.setenv("DB_PATH", str(tmp_path / "uc11.db"))
    monkeypatch.setenv("TRACE_DIR", str(tmp_path / "traces"))
    monkeypatch.delenv("WEATHER_SECOND_SOURCE", raising=False)
    init_db()
    monkeypatch.setattr("sys.argv", ["load_destination.py", "hue", "--complete"])
    load_destination.main()
    monkeypatch.setattr(weather, "_client", lambda: TestClient(mock.app, base_url="http://localhost:8081",
                                                               headers={"X-Mock-Mode": "normal"}))  # fmt: skip
    fx = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    trip_id = repo.create_trip("u-ha")
    repo.save_profile(trip_id, TripProfile.model_validate(fx["profile"]))
    run_id = repo.create_run("UC-11", trip_id, "u-ha")

    claims = verify_itinerary(Itinerary.model_validate(fx["itinerary"] | {"trip_id": trip_id}), run_id,
                              extractor=verify.extract_regex)  # fmt: skip
    got = {(c.target_id, c.claim_type, c.claim_text): c for c in claims}
    for e in fx["expected"]:
        c = got[(e["slot_id"], e["claim_type"], e["claim_text"])]
        assert c.status == e["status"], (e, c)
        assert c.status != "contradicted" or c.corrected_text  # schema: sai thì phải có giá trị đúng theo nguồn
    db_rows = repo.query("SELECT COUNT(*) AS n FROM claims WHERE run_id = ? AND target_type = 'itinerary_slot'", (run_id,))
    assert db_rows[0]["n"] == len(claims)
