"""Giãn request và retry 429/5xx hữu hạn, không ghi key/payload vào log."""

import json
import math
import os
import threading
import time
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse

from openai import APIConnectionError, APITimeoutError, InternalServerError, RateLimitError

from agent.db import repo

MAX_RETRIES = 2
MAX_RETRY_WAIT_SECONDS = 60
# Timeout của SDK (120 s) là giữa 2 lần nhận dữ liệu; OpenRouter gửi khoảng trắng giữ kết nối nên 1 lời gọi từng treo
# 12 phút (trace 18/11 r-f2cd4266). Đây là hạn TỔNG mỗi lời gọi; lâu nhất từng thành công khi đo là 201 s.
CALL_DEADLINE_SECONDS = float(os.environ.get("LLM_CALL_DEADLINE_SECONDS", "300"))
_PACERS = {}
_PACERS_LOCK = threading.Lock()


class LLMDeadlineError(TimeoutError):
    """Lời gọi LLM quá hạn tổng CALL_DEADLINE_SECONDS."""


def _call_with_deadline(fn, kwargs, seconds):
    """Chạy fn ở thread riêng, chờ tối đa `seconds`. Quá hạn thì bỏ kết quả (thread tự kết thúc khi kết nối đóng)."""
    box = {}

    def run():
        try:
            box["value"] = fn(**kwargs)
        except BaseException as error:  # noqa: BLE001 — chuyển nguyên lỗi về thread gọi
            box["error"] = error

    worker = threading.Thread(target=run, daemon=True, name="llm-call")
    worker.start()
    worker.join(seconds)
    if worker.is_alive():
        raise LLMDeadlineError(f"LLM không trả lời sau {seconds:.0f} s")
    if "error" in box:
        raise box["error"]
    return box["value"]


class RequestPacer:
    """Chung giữa tool turns/vòng replan và request đồng thời, theo endpoint + model."""

    def __init__(self):
        self.lock = threading.Lock()
        self.next_allowed = 0.0

    def wait(self, interval, run_id, node):
        with self.lock:
            delay = max(0.0, self.next_allowed - time.monotonic())
            if delay > 0:
                repo.log_event(run_id, node, "guardrail", name="llm_wait",
                               result={"seconds": round(delay, 3), "reason": "request_spacing_or_retry"})
                time.sleep(delay)
            self.next_allowed = time.monotonic() + interval

    def cooldown(self, seconds):
        with self.lock:
            self.next_allowed = max(self.next_allowed, time.monotonic() + seconds)


def _interval(client):
    host = urlparse(str(getattr(client, "base_url", ""))).hostname
    default = "5" if host == "generativelanguage.googleapis.com" else "0"
    try:
        seconds = float(os.environ.get("LLM_MIN_INTERVAL_SECONDS", default))
    except ValueError as error:
        raise ValueError("LLM_MIN_INTERVAL_SECONDS phải là số trong khoảng 0..120.") from error
    if not math.isfinite(seconds) or not 0 <= seconds <= 120:
        raise ValueError("LLM_MIN_INTERVAL_SECONDS phải là số hữu hạn trong khoảng 0..120.")
    return seconds


def _seconds(value):
    try:
        result = float(value)
    except (ValueError, TypeError, OverflowError):
        return None
    return result if math.isfinite(result) and result >= 0 else None


def retry_delay(error, attempt):
    """Ưu tiên Retry-After/RetryInfo; không có hint thì backoff 15s, 30s; thêm 1s biên an toàn."""
    hints = []
    headers = error.response.headers
    value = headers.get("retry-after")
    if value is not None:
        seconds = _seconds(value)
        if seconds is None:
            try:
                date = parsedate_to_datetime(value)
                if date.tzinfo is None:
                    date = date.replace(tzinfo=UTC)
                seconds = max(0, (date - datetime.now(UTC)).total_seconds())
            except (ValueError, TypeError, OverflowError):
                pass
        if seconds is not None:
            hints.append(seconds)
    milliseconds = _seconds(headers.get("retry-after-ms"))
    if milliseconds is not None:
        hints.append(milliseconds / 1000)
    # Google có thể trả error dưới dict hoặc list như log RESOURCE_EXHAUSTED.
    pending = [error.body]
    while pending:
        item = pending.pop()
        if isinstance(item, list):
            pending.extend(item)
        elif isinstance(item, dict):
            for key, value in item.items():
                if key == "retryDelay":
                    if isinstance(value, str) and value.endswith("s"):
                        seconds = _seconds(value[:-1])
                    elif isinstance(value, dict):
                        whole, nanos = _seconds(value.get("seconds", 0)), _seconds(value.get("nanos", 0))
                        seconds = whole + nanos / 1e9 if whole is not None and nanos is not None else None
                    else:
                        seconds = None
                    if seconds is not None:
                        hints.append(seconds)
                elif key.lower() == "x-ratelimit-reset":  # OpenRouter: epoch ms; hết quota ngày → chờ > 60s → dừng ngay
                    reset_ms = _seconds(value)
                    if reset_ms is not None:
                        hints.append(max(0, reset_ms / 1000 - datetime.now(UTC).timestamp()))
                elif isinstance(value, (dict, list)):
                    pending.append(value)
    return max(hints) + 1 if hints else min(15 * 2 ** attempt, MAX_RETRY_WAIT_SECONDS)


def request_completion(client, run_id, node, **kwargs):
    """Một lần gọi logic; tối đa 3 HTTP attempts khi 429/5xx. Không đổi model/key hoặc tăng quota."""
    interval = _interval(client)
    key = (str(getattr(client, "base_url", "")), kwargs.get("model"))
    with _PACERS_LOCK:
        pacer = _PACERS.setdefault(key, RequestPacer())
    for attempt in range(MAX_RETRIES + 1):
        pacer.wait(interval, run_id, node)
        try:
            return _call_with_deadline(client.chat.completions.create, kwargs, CALL_DEADLINE_SECONDS)
        except (RateLimitError, InternalServerError) as error:
            delay = retry_delay(error, attempt)
            if attempt == MAX_RETRIES or delay > MAX_RETRY_WAIT_SECONDS:
                repo.log_event(run_id, node, "guardrail", name="llm_retry_exhausted",
                               result={"status": error.status_code, "attempts": attempt + 1,
                                       "reason": "retry_limit" if attempt == MAX_RETRIES else "wait_exceeds_60s"})
                raise
            repo.log_event(run_id, node, "guardrail", name="llm_retry",
                           result={"status": error.status_code, "retry": attempt + 1, "max_retries": MAX_RETRIES,
                                   "seconds": round(delay, 3)})
            pacer.cooldown(delay)
        except APITimeoutError:
            raise  # đã chờ hết timeout 120 s: thử lại sẽ kéo dài vài phút, để node xử lý
        except (json.JSONDecodeError, APIConnectionError, LLMDeadlineError) as error:
            # Provider trả 200 nhưng body JSON hỏng / đứt kết nối / quá hạn tổng: lỗi tạm thời, trước đây làm hỏng cả lượt
            # lập lịch (trace 18/11 r-98408e05). Thử lại hữu hạn, backoff ngắn.
            if attempt == MAX_RETRIES:
                repo.log_event(run_id, node, "guardrail", name="llm_retry_exhausted",
                               result={"error": type(error).__name__, "attempts": attempt + 1, "reason": "retry_limit"})
                raise
            delay = 2.0 * (attempt + 1)
            repo.log_event(run_id, node, "guardrail", name="llm_retry",
                           result={"error": type(error).__name__, "retry": attempt + 1, "max_retries": MAX_RETRIES,
                                   "seconds": delay})
            pacer.cooldown(delay)
