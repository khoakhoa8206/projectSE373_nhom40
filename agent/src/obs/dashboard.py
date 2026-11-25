"""Dashboard vận hành tối thiểu (Buổi 11, slide 47): 5 chỉ số đọc từ bảng runs, trace_events, approvals do Host ghi.
1. Số lượt chạy, tỷ lệ thành công · 2. Token, chi phí mỗi lượt · 3. Latency p95 · 4. Tool lỗi nhiều nhất ·
5. Lượt bị chặn (guardrail) và chờ duyệt (approvals). Dùng cho GET /api/dashboard và scripts/dashboard.py."""

import math
from collections import Counter, defaultdict

USER = "(:user IS NULL OR r.user_id = :user)"


def p95(values):
    """Phân vị 95 kiểu nearest-rank (không nội suy); rỗng → None."""
    v = sorted(values)
    return v[math.ceil(0.95 * len(v)) - 1] if v else None


def summarize_runs(rows):
    """rows: (status, tokens, cost_usd, latency_ms). Tỷ lệ thành công chỉ tính lượt đã kết thúc (succeeded / failed);
    interrupted = đang chờ người dùng duyệt/trả lời, không phải lỗi. Token trung bình chỉ tính lượt có gọi LLM."""
    status = Counter(r[0] for r in rows)
    done = status["succeeded"] + status["failed"]
    tokens = [r[1] for r in rows if r[1]]
    return {
        "runs": len(rows),
        **{s: status[s] for s in ("succeeded", "failed", "interrupted", "running")},
        "success_rate": status["succeeded"] / done if done else None,
        "avg_tokens": sum(tokens) / len(tokens) if tokens else None,
        "max_tokens": max(tokens, default=None),
        "cost_usd": sum(r[2] or 0 for r in rows),
        "latency_p95_ms": p95([r[3] for r in rows if r[3] is not None]),
    }


def dashboard(conns, user_id=None, top=5):
    """Gộp nhiều DB (eval: mỗi case 1 DB). user_id = None → mọi người dùng (chỉ dùng cho script của nhóm)."""
    runs, tools, guards, approvals = defaultdict(list), [], Counter(), Counter()
    p = {"user": user_id}
    for conn in conns:
        for uc, *row in conn.execute(
            f"SELECT uc, status, tokens_in + tokens_out, cost_usd, latency_ms FROM runs r WHERE {USER}", p
        ):
            runs[uc].append(row)
        tools += [tuple(r) for r in conn.execute(  # tuple(): conn của repo dùng sqlite3.Row
            f"""SELECT e.name, e.error IS NOT NULL FROM trace_events e JOIN runs r USING (run_id)
                WHERE e.kind = 'tool_call' AND {USER}""", p)]  # fmt: skip
        guards.update(
            n
            for (n,) in conn.execute(
                f"SELECT e.name FROM trace_events e JOIN runs r USING (run_id) WHERE e.kind = 'guardrail' AND {USER}", p
            )
        )
        approvals.update(
            tuple(r)
            for r in conn.execute(  # trips cũng có user_id: dùng chung điều kiện USER (alias r)
                f"SELECT a.kind, a.decision FROM approvals a JOIN trips r USING (trip_id) WHERE {USER}", p
            )
        )
    calls, errors = Counter(n for n, _ in tools), Counter(n for n, failed in tools if failed)
    worst = sorted(calls, key=lambda n: (-errors[n], -calls[n], n))[:top]
    return {
        "total": summarize_runs([r for rows in runs.values() for r in rows]),
        "by_uc": {uc: summarize_runs(rows) for uc, rows in sorted(runs.items())},
        "tools": [
            {"name": n, "calls": calls[n], "errors": errors[n], "error_rate": errors[n] / calls[n]} for n in worst
        ],
        "guardrails": dict(guards.most_common()),
        "approvals": {
            "pending": sum(c for (_, d), c in approvals.items() if d == "pending"),
            "by_kind": {f"{k}:{d}": c for (k, d), c in sorted(approvals.items())},
        },
    }
