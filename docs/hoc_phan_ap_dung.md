# Nhóm 40 đã học gì và áp dụng vào Tour Guide Agent như thế nào

Bám theo bảng "Mười một buổi: agent = model + harness" (Buổi 11, slide 51). Mỗi dòng: khái niệm → chỗ áp dụng trong
repo → bằng chứng chạy được. Dùng cho chương "Quá trình học và áp dụng" của báo cáo và để trả lời vấn đáp.

**Kiến trúc một câu:** workflow LangGraph (code quyết luồng giữa các node) + agent loop bên trong node cần suy luận
(model chọn tool) + harness bao quanh (validator, verifier, approval, trace, eval). Model thuê qua OpenRouter; phần nhóm
xây là harness.

## Buổi 01 · Tổng quan Agentic AI: ba câu hỏi phân loại hệ thống

| Câu hỏi | Tour Guide Agent |
|---|---|
| Ai quyết bước sau? | Giữa các node: **code** (graph `intake → plan → validate → … → approve`). Trong node `plan`: **model** chọn tool nào gọi |
| Ai giữ state? | **Hệ thống**: SQLite (`runs`, `itineraries`, `approvals`…) + checkpoint LangGraph ([agent/src/graph/checkpoint.py](../agent/src/graph/checkpoint.py)) |
| Ai dừng vòng lặp? | Model nộp `submit_result` **và** trần cứng của harness: `max_turns = 15`, planner ≤ 4 vòng, UC-06 ≤ 2 vòng review |

Quy tắc dùng AI (minh bạch, kiểm chứng, giải thích được) → [docs/ai_usage.md](ai_usage.md).

## Buổi 02 · Nguyên lý LLM-powered app

| Khái niệm | Áp dụng | Bằng chứng |
|---|---|---|
| Structured Output | Kết quả mọi node LLM là model Pydantic (`Itinerary`, `NarrationDraft`, `IntakeResult`…), nộp qua tool ảo `submit_result`; sai schema → gửi lỗi cho LLM tự sửa | [loop.py](../agent/src/graph/loop.py) `agent_loop`, `_handle_call` |
| Function Calling | Tool schema sinh từ type hint + docstring (`tool_spec`); `run_id` harness tự truyền, LLM không thấy | `tool_spec`, `run_tool` |
| Context Engineering | Planner nhận `verified_context` (giờ mở cửa, thời gian đi lại đã tra sẵn) thay vì để LLM tự đoán | [plan.py](../agent/src/nodes/plan.py) `prepare_context` |
| Token, chi phí | Cộng `usage` mỗi lượt → `runs.tokens_in/out`, `cost_usd` | `repo.finish_run`, dashboard mục 9 của [security.md](security.md) |

## Buổi 03 · Agent fundamentals

| Khái niệm | Áp dụng |
|---|---|
| agent = goal + tools + loop + termination | `agent_loop(system, user, tools, output, max_turns)` |
| Điều kiện dừng kiểm chứng được | Nộp kết quả hợp lệ schema; hết lượt → `AgentLoopLimitError`; 2 lượt cuối ép `tool_choice = submit_result`; `finish_reason = length` → lỗi rõ ràng |
| Reflection / tự sửa | Vòng `plan → validate` (validator bằng code trả `Violation`) → `plan` sửa theo vi phạm, giữ bản tốt nhất |
| Plan-then-execute | UC-02 lập lịch cả chuyến rồi kiểm từng slot |
| Debug bằng trace | Mỗi node/LLM/tool/guardrail là 1 dòng `trace_events`; trace mẫu ở `traces/samples/uc-xx/` |

## Buổi 04 · Từ Prompt Engineering đến Skill

Prompt dài tách thành skill tái dùng: [skills/](../skills/) (`trip-intake`, `itinerary-planning`, `site-narration`,
`trip-journal`; `fact-check-travel-info` của UC-11). Nạp bằng `load_skill` (chỉ đọc markdown, tên `[a-z0-9-]+`), trace
ghi `skill_use`. Mỗi SKILL.md có: khi dùng / không dùng, I/O, quy trình, ràng buộc, ví dụ, final check.

## Buổi 05 · Harness và Tool

- Tool trả lỗi cho LLM thay vì làm sập lượt chạy (`run_tool`).
- Validator thuần code, không gọi LLM: [validation/validator.py](../agent/src/validation/validator.py),
  `check_fabrication` chặn POI/giá bịa.
- Không có nguồn → `NULL` + nhãn "chưa xác minh", không ước đoán (AGENTS.md).

## Buổi 06 · RAG và Knowledge Harness

| Khái niệm | Áp dụng | Số đo |
|---|---|---|
| Chunk = text + metadata | [kb/catalog.csv](../kb/catalog.csv) (nguồn, giấy phép, ngôn ngữ, `doc_type`, `is_fictional`); chunk theo mục, `chunk_id = <doc_id>:c<i>` (nạp lại không trùng) | [rag/ingest.py](../agent/src/rag/ingest.py) |
| Một embedding model cho 2 pha | `paraphrase-multilingual-MiniLM-L12-v2` (hỏi tiếng Việt, tìm được tài liệu tiếng Anh) | [rag/retriever.py](../agent/src/rag/retriever.py) |
| Grounding, Citation | Mỗi ý có `[doc_id §section]` + quote nguyên văn, kiểm bằng code | [validation/citations.py](../agent/src/validation/citations.py) |
| Abstention | Điểm truy xuất thấp → `out_of_kb` + câu mẫu, không gọi LLM | guardrail `kb_min_score` |
| Đo bằng số | Recall@5, citations_valid, out_of_kb_ok, injection_ok | [evals/uc03/README.md](../evals/uc03/README.md) |

## Buổi 07 · Memory, State, Context

| Khái niệm | Áp dụng |
|---|---|
| Persistent memory | UC-07: lưu sở thích sau chuyến, chỉ mục người dùng chọn; mục nhạy cảm cần đồng ý riêng, thu hồi được, có hạn ([memory/store.py](../agent/src/memory/store.py)) |
| Compaction | UC-09 tóm tắt theo tầng (ngày → chuyến), ghi `tokens_before → tokens_after` |
| State bền qua restart | Checkpoint LangGraph trong SQLite; `recover_runs` chạy tiếp lượt dở |
| Model switching | `LLM_MODEL` là danh sách model dự phòng |

## Buổi 08 · Workflow, Multi-agent, Interrupt

| Khái niệm | Áp dụng |
|---|---|
| Code điều khiển luồng | Graph LangGraph có cạnh điều kiện, bộ đếm `round` để chặn vòng lặp ([app.py](../agent/src/graph/app.py)) |
| Human-in-the-loop | `interrupt()` + checkpointer + `thread_id = trip_id`; thao tác ghi đặt sau `interrupt()` |
| Phân quyền theo rủi ro | Đọc tự động; ghi (chốt lịch trình, lưu bộ nhớ) phải duyệt |
| Multi-agent | UC-06: 3 reviewer chỉ đọc chạy song song (chuyên gia địa phương, ngân sách, an toàn), trao đổi bằng `ReviewFinding` có cấu trúc |

## Buổi 09 · Trace, Verifier, Eval Set, Regression

- Trace: `repo.log_event` ghi song song DB + `traces/<run_id>.jsonl`; trace viewer trên PWA.
- Verifier: UC-11 kiểm từng claim (giờ mở cửa, giá, thời tiết, lễ hội) trước khi trả cho người dùng.
- Eval runner: `python -m evals.run --all --name run1` → mỗi case 1 DB riêng, mock thời tiết theo case, scorer chỉ đọc DB;
  agent không đọc được `evals/`.
- Regression: `results/run1` so với `results/run2` (trang Eval, `results/regression.md`).

## Buổi 11 · MCP và An toàn

Xem [docs/security.md](security.md): bảng phân quyền tool, Lethal Trifecta theo UC, Approval Gate + Audit Log, test
prompt injection, secret/PII, fallback, dashboard 5 chỉ số (`GET /api/dashboard`, `scripts/dashboard.py`). MCP: UC-10.
