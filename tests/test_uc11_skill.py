"""W10-P4-5: skill fact-check-travel-info đủ hợp đồng và thật sự được nạp khi tách claim bằng LLM; thời tiết ngoài miền
(48 °C ở Huế) bị đánh dấu bất thường 100 % và không bao giờ thành claim verified. LLM giả, mock-weather trong tiến trình."""

import json
import re
import typing
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agent.db import repo
from agent.src.nodes import verify
from agent.src.nodes.verify import LlmClaim, LlmClaims
from agent.src.tools import weather
from mocks.mock_weather import app as mock

SKILL = Path(__file__).resolve().parents[1] / "skills" / "fact-check-travel-info" / "SKILL.md"
SECTIONS = ["## Khi dùng / không dùng", "## Input / output", "## Quy trình", "## Ràng buộc", "## Ví dụ", "## Final check"]


def test_skill_contract():
    text = SKILL.read_text(encoding="utf-8")
    front = re.match(r"---\nname: (.+)\ndescription: (.+)\n---\n", text)
    assert front and front[1] == "fact-check-travel-info" == verify.SKILL and front[2].strip()
    assert [s for s in SECTIONS if s not in text] == []  # cùng khung với skills/itinerary-planning
    for name in typing.get_args(verify.Attribute) + typing.get_args(verify.ClaimType):
        assert f"`{name}`" in text, f"skill chưa nói tới {name}"
    example = json.loads(re.search(r"```json\n(.*?)\n```", text, re.DOTALL)[1])
    assert LlmClaims.model_validate(example).claims  # ví dụ trong skill đúng schema LLM phải nộp
    assert not re.search(r"```(?:bash|sh|python)", text)  # skill chỉ là Markdown, không có lệnh để chạy


@pytest.fixture
def run_id(db, monkeypatch):
    repo.query("UPDATE pois SET ticket_price_vnd = 200000, opening_hours = 'Mo-Su 08:00-17:00' WHERE poi_id = 'hue-dai-noi'")
    return repo.create_run("UC-11", repo.create_trip("u-ha"), "u-ha")


def use_mock(monkeypatch, mode):
    monkeypatch.setattr(weather, "_client", lambda: TestClient(mock.app, base_url="http://localhost:8081",
                                                               headers={"X-Mock-Mode": mode}))  # fmt: skip


def test_llm_extraction_uses_skill(run_id, monkeypatch):
    seen = []

    def loop(client, system, user, tools, output, run_id, node, usage, max_turns):
        seen.append(system)
        return LlmClaims(claims=[LlmClaim(claim_type="price", attribute="adult_price", claim_text="150.000đ",
                                          value="150.000đ", poi_id="hue-dai-noi")])  # fmt: skip

    monkeypatch.setattr(verify, "agent_loop", loop)
    monkeypatch.setattr(verify, "make_client", lambda: None)
    claims = verify.verify_text("Vé Đại Nội 150.000đ.", run_id, ctx={"destination_id": "hue", "lang": "vi"})
    assert seen == [SKILL.read_text(encoding="utf-8")]
    assert [(c.claim_text, c.status) for c in claims] == [("150.000đ", "contradicted")]
    used = repo.query("SELECT name FROM trace_events WHERE run_id = ? AND kind = 'skill_use'", (run_id,))
    assert [r["name"] for r in used] == ["fact-check-travel-info"]


@pytest.mark.parametrize("month", range(1, 13))
def test_48c_in_hue_is_anomalous_every_month(month):
    day = date(2026, month, 15)
    reasons = weather._anomaly({"forecast_date": day.isoformat(), "temp_min_c": 30.0, "temp_max_c": 48.0, "precip_mm": 0.0,
                                "condition": "clear"}, "hue", day)  # fmt: skip
    assert any("48.0 °C ngoài miền khí hậu Huế" in r for r in reasons)


def test_abnormal_weather_never_verified_whole_trip(run_id, monkeypatch):
    use_mock(monkeypatch, "abnormal")  # mock trả 41–48 °C, mưa -3 mm cho mọi ngày (case tấn công số 5)
    days = ["2026-11-25", "2026-11-26", "2026-11-27"]
    text = " ".join(f"Ngày {d[8:]}/11 trời {t} °C, mưa {m} mm." for d, t, m in zip(days, (48, 47, 30), (0, 5, 2)))
    res = verify.verify_and_fix(text, run_id, ctx={"destination_id": "hue", "trip_dates": [days[0], days[-1]], "lang": "vi"},
                                extractor=verify.extract_regex)  # fmt: skip
    weather_claims = [c for c in res["claims"] if c.claim_type == "weather"]
    assert len(weather_claims) == 6 and {c.status for c in weather_claims} == {"unverified"}
    assert res["text"].count("(chưa xác minh)") == 3  # mỗi câu một nhãn
    snaps = repo.weather_for_run(run_id)
    assert sorted(snaps) == days and all(s["is_anomalous"] for s in snaps.values())
    reasons = [json.loads(r["result"])["reason"] for r in repo.query(
        "SELECT result FROM trace_events WHERE run_id = ? AND name = 'claim'", (run_id,))]  # fmt: skip
    assert reasons == ["weather_anomalous"] * 6  # lý do "bất thường" có trong trace, không lẫn với "không có nguồn"
