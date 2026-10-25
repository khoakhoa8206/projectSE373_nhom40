"""Cơ chế chung cho node có LLM (P1): gọi API tương thích OpenAI, kèm tool, skill và trace.
Node chỉ cần gọi agent_loop(...) với prompt + danh sách tool + model Pydantic của kết quả."""

import inspect
import json
import os
import re
import time
from pathlib import Path
from typing import Any, get_type_hints

from openai import OpenAI
from pydantic import BaseModel, ValidationError, create_model
from pydantic_core import to_jsonable_python

from agent.db import repo
from agent.src.graph.llm_requests import request_completion

OPENROUTER_URL = "https://openrouter.ai/api/v1"
# Thứ tự ưu tiên: model đầu lỗi / bị giới hạn thì OpenRouter tự thử model sau. Ghi đè bằng LLM_MODEL trong .env.
DEFAULT_MODELS = (
    "nvidia/nemotron-3-ultra-550b-a55b:free,nvidia/nemotron-3.5-super-vl:free,dots-studio/dots-3-note-preview:free"
)
SUBMIT = "submit_result"  # tool ảo: LLM gọi để nộp kết quả cuối, chạy được với mọi model có tool calling
SKILLS_DIR = Path(__file__).resolve().parents[3] / "skills"


class AgentLoopLimitError(RuntimeError):
    """Hết ngân sách tool turns mà chưa có structured output hợp lệ."""


def ms(t0):
    return int((time.perf_counter() - t0) * 1000)


def make_client():
    return OpenAI(
        base_url=os.environ.get("LLM_BASE_URL", OPENROUTER_URL),
        api_key=os.environ.get("LLM_API_KEY"),
        timeout=120,
        max_retries=0,  # retry 429/5xx do request_completion quản lý, tránh SDK âm thầm gọi dồn
    )


def model_names():
    return [m.strip() for m in os.environ.get("LLM_MODEL", DEFAULT_MODELS).split(",") if m.strip()]


def load_skill(name, run_id, node):
    """Nạp skills/<name>/SKILL.md vào prompt. Chỉ đọc markdown trong skills/, không chạy script nào."""
    if not re.fullmatch(r"[a-z0-9-]+", name):
        raise ValueError(f"tên skill không hợp lệ: {name!r}")
    text = (SKILLS_DIR / name / "SKILL.md").read_text(encoding="utf-8")
    repo.log_event(run_id, node, "skill_use", name=name)
    return text


def json_schema(model: type[BaseModel]):
    """JSON Schema không có $ref (một số provider của model free không đọc được $defs)."""
    schema = model.model_json_schema()
    defs = schema.pop("$defs", {})

    def inline(x):
        if isinstance(x, dict):
            return inline(defs[x["$ref"].rsplit("/", 1)[-1]]) if "$ref" in x else {k: inline(v) for k, v in x.items()}
        return [inline(v) for v in x] if isinstance(x, list) else x

    return inline(schema)


def tool_spec(fn):
    """Tool definition sinh từ chữ ký hàm (type hint + docstring). run_id do harness tự truyền, LLM không thấy."""
    hints = get_type_hints(fn)
    fields = {
        n: (hints.get(n, Any), ... if p.default is p.empty else p.default)
        for n, p in inspect.signature(fn).parameters.items()
        if n != "run_id"
    }
    return {"type": "function", "function": {
        "name": fn.__name__,
        "description": inspect.getdoc(fn) or fn.__name__,
        "parameters": json_schema(create_model(fn.__name__, **fields)),
    }}  # fmt: skip


def run_tool(fn, args, run_id, node):
    """Gọi 1 tool và ghi tool_call. Lỗi được trả về cho LLM tự xử lý thay vì làm sập lượt chạy."""
    if "run_id" in inspect.signature(fn).parameters:
        args = args | {"run_id": run_id}
    t0 = time.perf_counter()
    try:
        result, error = to_jsonable_python(fn(**args), fallback=str), None
    except Exception as e:  # noqa: BLE001 — lỗi tool trả về cho LLM
        result, error = None, f"{type(e).__name__}: {e}"
    repo.log_event(run_id, node, "tool_call", name=fn.__name__, args=args, result=result, duration_ms=ms(t0),
                   error=error)  # fmt: skip
    return result, error


def _handle_call(call, by_name, output, run_id, node):
    """(kết quả cuối, None) nếu LLM nộp hợp lệ; ngược lại (None, nội dung trả về cho LLM)."""
    try:
        args = json.loads(call.function.arguments or "{}")
        if call.function.name == SUBMIT:
            return output.model_validate(args), None
    except (json.JSONDecodeError, ValidationError) as e:
        return None, json.dumps({"error": f"Tham số không hợp lệ, sửa và gọi lại: {e}"}, ensure_ascii=False)
    fn = by_name.get(call.function.name)
    result, error = run_tool(fn, args, run_id, node) if fn else (None, f"không có tool {call.function.name}")
    return None, json.dumps({"error": error} if error else result, ensure_ascii=False)


def agent_loop(client, system, user, tools, output: type[BaseModel], run_id, node, usage, max_turns=15):
    """Vòng tool-calling: LLM gọi tool tới khi nộp kết quả qua tool SUBMIT (schema = `output`).
    Kết quả sai ràng buộc Pydantic thì gửi lỗi lại cho LLM tự sửa. `usage` cộng dồn token + chi phí cả lượt chạy."""
    by_name = {f.__name__: f for f in tools}
    specs = [tool_spec(f) for f in tools] + [{"type": "function", "function": {
        "name": SUBMIT, "description": "Nộp kết quả cuối cùng khi đã đủ dữ liệu.", "parameters": json_schema(output),
    }}]  # fmt: skip
    names = model_names()
    instruction = f"{system}\n\nKhi xong, gọi tool {SUBMIT} với kết quả cuối, không trả lời bằng văn bản."
    messages = [
        {"role": "system", "content": instruction},
        {"role": "user", "content": user},
    ]  # fmt: skip
    for turn in range(max_turns):
        remaining = max_turns - turn
        messages[0]["content"] = (f"{instruction}\nNgân sách vòng này: còn {remaining}/{max_turns} lượt LLM. "
                                  "Gom tra cứu độc lập vào cùng lượt tool calls, không hỏi lại facts đã có/unknown. "
                                  f"Đủ dữ kiện thì nộp {SUBMIT}, không cần dùng hết lượt.")
        force_submit = remaining <= min(2, max_turns)
        # OpenRouter tự chuyển model sau khi model đầu lỗi/bị giới hạn; Google không nhận trường này.
        options = {"extra_body": {"models": names}} if "openrouter.ai" in str(getattr(client, "base_url", "")) else {}
        if force_submit:
            options["tool_choice"] = {"type": "function", "function": {"name": SUBMIT}}
            messages.append({"role": "user", "content": (
                f"Còn {remaining} lượt. Không tra cứu thêm. Dùng dữ kiện đã có để gọi {SUBMIT} ngay; "
                "giữ null/unverified nếu thiếu, không bịa. Nộp bản bảo thủ và ghi rõ giới hạn chưa đáp ứng.")})
            repo.log_event(run_id, node, "guardrail", name="require_submission",
                           result={"turn": turn + 1, "remaining": remaining})
        t0 = time.perf_counter()
        resp = request_completion(
            client, run_id, node,
            model=names[0],
            messages=messages,
            tools=specs,
            max_tokens=16000,
            **options,
        )
        if not resp.choices:
            raise RuntimeError(f"{node}: LLM provider không trả kết quả: {resp}")
        msg, finish = resp.choices[0].message, resp.choices[0].finish_reason
        calls = msg.tool_calls or []
        usage["in"] += resp.usage.prompt_tokens
        usage["out"] += resp.usage.completion_tokens
        usage["cost"] += getattr(resp.usage, "cost", 0) or 0  # model :free thì = 0
        repo.log_event(run_id, node, "llm_call", name=resp.model, duration_ms=ms(t0), tokens=resp.usage.total_tokens,
                       result={"finish_reason": finish, "tool_calls": [c.function.name for c in calls]})  # fmt: skip
        if finish == "length":
            raise RuntimeError(f"{node}: LLM bị cắt vì hết max_tokens")
        messages.append(msg.model_dump(exclude_none=True))  # giữ cả reasoning_details để model suy luận tiếp

        if not calls:  # model yếu đôi khi trả JSON dạng văn bản thay vì gọi tool nộp
            try:
                return output.model_validate_json(re.sub(r"^```(?:json)?|```$", "", (msg.content or "").strip()))
            except ValidationError:
                messages.append({"role": "user", "content": f"Hãy gọi tool {SUBMIT} với kết quả cuối."})
                continue
        for call in calls:
            done, content = _handle_call(call, by_name, output, run_id, node)
            if done is not None:
                return done
            messages.append({"role": "tool", "tool_call_id": call.id, "content": content})
    raise AgentLoopLimitError(f"{node}: quá {max_turns} lượt gọi LLM mà chưa có kết quả hợp lệ")
