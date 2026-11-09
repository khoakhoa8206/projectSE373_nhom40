"""Chỉ xác nhận các artifact live thật sự có; không dựng fixture giả để xanh CI."""

from pathlib import Path

import pytest

from agent.schemas import Itinerary
from scripts.export_phase2_examples import EXAMPLES

FOLDER = Path(__file__).resolve().parents[1] / "evals/fixtures/itineraries"


def test_live_export_defines_three_required_scenarios():
    assert set(EXAMPLES) == {"thu-ha-3-days", "english-2-days", "low-budget"}
    assert EXAMPLES["thu-ha-3-days"]["budget_total_vnd"] == 8000000
    assert EXAMPLES["english-2-days"]["language"] == "en"


@pytest.mark.skipif(not any((FOLDER / f"{name}.json").exists() for name in EXAMPLES),
                    reason="Chưa có 3 artifact từ LLM thật; user sẽ chạy sau khi có API key")
def test_three_live_itineraries_match_shared_schema():
    for name in EXAMPLES:
        path = FOLDER / f"{name}.json"
        assert path.exists(), f"Thiếu artifact live {name}; không coi bộ ví dụ đã hoàn tất"
        itinerary = Itinerary.model_validate_json(path.read_text(encoding="utf-8"))
        assert itinerary.run_id and itinerary.status != "approved"
