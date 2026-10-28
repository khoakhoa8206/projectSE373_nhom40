"""Giả lập Google 429 và thời gian; không mạng, không dùng key thật, không sleep thật."""

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from types import SimpleNamespace

import httpx
import pytest
from openai import AuthenticationError, InternalServerError, OpenAI, RateLimitError
from pydantic import BaseModel

from agent.db import repo
from agent.src.graph import llm_requests, loop

GOOGLE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
MODEL = "gemini-3.5-flash-lite"
COMPLETION = {
    "id": "test", "object": "chat.completion", "created": 0, "model": MODEL,
    "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": '{"ok":true}'}}],
    "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
}


@pytest.fixture
def clock(db, monkeypatch):
    clock = SimpleNamespace(now=1000.0, sleeps=[], calls=[], run_id=repo.create_run("UC-02", None, "u-ha"))

    def sleep(seconds):
        assert 0 <= seconds <= 120
        clock.sleeps.append(seconds)
        clock.now += seconds

    monkeypatch.delenv("LLM_MIN_INTERVAL_SECONDS", raising=False)
    monkeypatch.setattr(llm_requests, "_PACERS", {})
    monkeypatch.setattr(llm_requests.time, "monotonic", lambda: clock.now)
    monkeypatch.setattr(llm_requests.time, "sleep", sleep)
    return clock


def client_for(handler):
    return OpenAI(base_url=GOOGLE_URL, api_key="test-only", max_retries=0,
                  http_client=httpx.Client(transport=httpx.MockTransport(handler)))


def request(client, clock):
    return llm_requests.request_completion(client, clock.run_id, "plan", model=MODEL,
                                           messages=[{"role": "user", "content": "test"}])


def test_google_spacing_shared_between_clients(clock):
    def respond(req):
        clock.calls.append(clock.now)
        return httpx.Response(200, json=COMPLETION)

    with client_for(respond) as first, client_for(respond) as second:
        request(first, clock)
        request(second, clock)  # không reset limiter khi client/vòng plan mới
        request(first, clock)
    assert clock.calls == [1000, 1005, 1010]
    assert clock.sleeps == [5, 5]
    events = repo.query("SELECT name FROM trace_events WHERE run_id=?", (clock.run_id,))
    assert [event["name"] for event in events] == ["llm_wait", "llm_wait"]


def test_google_retryinfo_list_then_success(clock):
    def respond(req):
        clock.calls.append(clock.now)
        if len(clock.calls) == 1:
            return httpx.Response(429, json=[{"error": {"code": 429, "details": [
                {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "9.399492128s"}]}}])
        return httpx.Response(200, json=COMPLETION)

    with client_for(respond) as client:
        assert request(client, clock).choices
    assert len(clock.calls) == 2
    assert clock.sleeps == pytest.approx([10.399492128])
    events = repo.query("SELECT result FROM trace_events WHERE run_id=? AND name='llm_retry'", (clock.run_id,))
    assert json.loads(events[0]["result"])["retry"] == 1
    assert "test-only" not in str(events)


def test_retry_exhaustion_is_bounded(clock):
    def respond(req):
        clock.calls.append(clock.now)
        return httpx.Response(429, headers={"Retry-After": "9"}, json={"error": {"message": "quota"}})

    with client_for(respond) as client, pytest.raises(RateLimitError):
        request(client, clock)
    assert len(clock.calls) == 3 and clock.sleeps == [10, 10]
    event = repo.query("SELECT result FROM trace_events WHERE name='llm_retry_exhausted'")[0]
    assert json.loads(event["result"])["attempts"] == 3


def test_missing_retry_hint_uses_backoff(clock):
    def respond(req):
        clock.calls.append(clock.now)
        return httpx.Response(429, json={"error": {"message": "quota"}})

    with client_for(respond) as client, pytest.raises(RateLimitError):
        request(client, clock)
    assert clock.sleeps == [15, 30]


def test_long_quota_wait_does_not_retry_early(clock):
    def respond(req):
        clock.calls.append(clock.now)
        return httpx.Response(429, headers={"Retry-After": "3600"}, json={"error": {"message": "daily quota"}})

    with client_for(respond) as client, pytest.raises(RateLimitError):
        request(client, clock)
    assert len(clock.calls) == 1 and clock.sleeps == []


def test_wrong_key_is_not_retried(clock):
    def respond(req):
        clock.calls.append(clock.now)
        return httpx.Response(401, json={"error": {"message": "test authentication error"}})

    with client_for(respond) as client, pytest.raises(AuthenticationError):
        request(client, clock)
    assert len(clock.calls) == 1 and clock.sleeps == []


@pytest.mark.parametrize("status", [500, 502, 503, 504])
def test_transient_server_error_then_success(clock, status):
    def respond(req):
        clock.calls.append(clock.now)
        if len(clock.calls) == 1:
            return httpx.Response(status, json=[{"error": {"code": status, "status": "UNAVAILABLE"}}])
        return httpx.Response(200, json=COMPLETION)

    with client_for(respond) as client:
        assert request(client, clock).choices
    assert len(clock.calls) == 2 and clock.sleeps == [15]
    event = repo.query("SELECT result FROM trace_events WHERE name='llm_retry'")[0]
    assert json.loads(event["result"])["status"] == status


def test_server_overload_retry_exhaustion_is_bounded(clock):
    def respond(req):
        clock.calls.append(clock.now)
        return httpx.Response(503, json={"error": {"message": "high demand"}})

    with client_for(respond) as client, pytest.raises(InternalServerError):
        request(client, clock)
    assert len(clock.calls) == 3 and clock.sleeps == [15, 30]
    event = repo.query("SELECT result FROM trace_events WHERE name='llm_retry_exhausted'")[0]
    assert json.loads(event["result"])["status"] == 503


@pytest.mark.parametrize("headers,body,expected", [
    ({"Retry-After": "2.5"}, None, 3.5),
    ({"retry-after-ms": "2500"}, None, 3.5),
    ({"Retry-After": "3"}, {"error": {"details": [{"retryDelay": "9s"}]}}, 10),
    ({}, {"error": {"details": [{"retryDelay": {"seconds": "4", "nanos": 500000000}}]}}, 5.5),
    ({"Retry-After": "NaN"}, {"retryDelay": "NaNs"}, 15),
    ({"Retry-After": "bad"}, None, 15),
    ({}, {"retryDelay": "-3s"}, 15),
])
def test_retry_hint_formats(headers, body, expected):
    response = httpx.Response(429, headers=headers, request=httpx.Request("POST", GOOGLE_URL))
    error = RateLimitError("test", response=response, body=body)
    assert llm_requests.retry_delay(error, 0) == expected


def test_openrouter_daily_quota_reset_stops_retry():
    reset = int((datetime.now(UTC) + timedelta(hours=10)).timestamp() * 1000)
    body = {"error": {"code": 429, "metadata": {"headers": {"X-RateLimit-Reset": str(reset)}}}}
    response = httpx.Response(429, request=httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions"))
    assert llm_requests.retry_delay(RateLimitError("test", response=response, body=body), 0) > 60


def test_retry_after_http_date():
    date = format_datetime(datetime.now(UTC) + timedelta(seconds=20), usegmt=True)
    response = httpx.Response(429, headers={"Retry-After": date}, request=httpx.Request("POST", GOOGLE_URL))
    assert 19 <= llm_requests.retry_delay(RateLimitError("test", response=response, body=None), 0) <= 21


@pytest.mark.parametrize("value", ["-1", "nan", "inf", "121", "not-a-number"])
def test_bad_interval_is_rejected(clock, monkeypatch, value):
    monkeypatch.setenv("LLM_MIN_INTERVAL_SECONDS", value)
    with pytest.raises(ValueError, match="LLM_MIN_INTERVAL_SECONDS"):
        llm_requests._interval(SimpleNamespace(base_url=GOOGLE_URL))


def test_other_providers_default_no_pacing(clock, monkeypatch):
    assert llm_requests._interval(SimpleNamespace(base_url="https://openrouter.ai/api/v1/")) == 0
    assert llm_requests._interval(SimpleNamespace()) == 0
    monkeypatch.setenv("LLM_MIN_INTERVAL_SECONDS", "6")
    assert llm_requests._interval(SimpleNamespace(base_url=GOOGLE_URL)) == 6


def test_parallel_requests_share_spacing(clock):
    def respond(req):
        clock.calls.append(clock.now)
        return httpx.Response(200, json=COMPLETION)

    with client_for(respond) as client, ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda _: request(client, clock), range(2)))
    assert clock.sleeps == [5]


def test_agent_loop_uses_pacer_across_replans(clock, monkeypatch):
    class Result(BaseModel):
        ok: bool

    def respond(req):
        clock.calls.append(clock.now)
        return httpx.Response(200, json=COMPLETION)

    monkeypatch.setenv("LLM_MODEL", MODEL)
    usage = {"in": 0, "out": 0, "cost": 0.0}
    with client_for(respond) as client:
        for _ in range(2):
            assert loop.agent_loop(client, "test", "test", [], Result, clock.run_id, "plan", usage).ok
    assert clock.sleeps == [5]
    assert usage == {"in": 20, "out": 10, "cost": 0.0}


def test_make_client_disables_hidden_sdk_retries(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "test-only")
    monkeypatch.setenv("LLM_BASE_URL", GOOGLE_URL)
    with loop.make_client() as client:
        assert str(client.base_url) == GOOGLE_URL
        assert client.max_retries == 0
