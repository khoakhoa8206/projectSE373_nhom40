# Bàn giao P2 · Ngô Hoàng Khang

Ngày 25/10/2026 · nhánh local `feat/P2-khang` · base `7798e1d`.
**Gói triển khai Phase 1 sẵn để teammate review, chưa commit/push/PR.** Không phải tuyên bố cả đồ án/UC-01 cuối kỳ đã xong.

## Đã làm
- 30 POI (15 tham quan/10 ăn/5 lưu trú) + attribution/license; ID khớp 4 POI KB P3 đang dùng.
- 5 polygon OSM landuse=military, giữ nguyên hình học; không bịa phạm vi cảnh báo hoặc nhận là vùng cấm pháp lý.
- 900 cặp drive có hướng từ OSRM, CSV + provenance, chạy demo không cần gọi routing lại.
- Checker và loader CSV/GeoJSON/matrix qua repo, `DB_PATH`, validate trước ghi, 1 transaction, upsert.
- Bốn tool đọc theo contract, lọc metadata bảo thủ, parser opening_hours có giới hạn rõ.
- 4 rule Phase 1 + fabrication; core overload/restricted_area và test bổ sung cho Phase 2.
- Prompt/skill UC-02, preflight search/forecast có trace; ghi nhãn thiếu giá/dự báo.
- Fix tích hợp nhỏ: giữ best draft thay bản cuối, lỗi POI bịa không gây FK crash, NULL total không hiển thị như miễn phí.
- Đặc tả UC-01/02, nguồn/licensing, AI usage; ghi bài ôn ngoài repo ở folder skill của Khang.

## Chạy nhanh trên Windows (PowerShell trong repo)
```powershell
# Nếu đã có .venv thì dùng lại, không cần cài lại.
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
$env:PYTHONUTF8 = "1"

# DB mới để tránh mất dữ liệu; agent.db.init SẼ XOÁ DB đích nếu đã tồn tại.
$env:DB_PATH = Join-Path $env:TEMP ("hue-demo-" + [guid]::NewGuid().ToString("N") + ".db")
.\.venv\Scripts\python.exe -m agent.db.init
.\.venv\Scripts\python.exe scripts/load_destination.py hue --complete

.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m pytest -q
npm.cmd --prefix web ci --ignore-scripts
npm.cmd --prefix web run build
```
Tương đương `make test` là hai lệnh Ruff + pytest trên (máy Khang chưa có make trong PATH).
`make db` nay init rồi nạp bundle: không dùng trên DB cần giữ.
DB_PATH phải được đặt trong **terminal chạy backend/dev**, biến môi trường ở terminal khác không tự truyền sang.

Demo live: tự cấu hình `LLM_API_KEY` OpenRouter trong `.env` theo `.env.example` (không commit/chia sẻ key),
sau đó `python scripts/dev.py`, mở `http://localhost:5173`. Xem README và trace trong UI.
Live demo phụ thuộc provider/tool-calling, mạng, quota/model và mock-weather. Chưa gọi LLM thật trong lượt bàn giao này.

## Kết quả kiểm chứng
- Data checker: 30 POI hợp lệ, **22 chưa có giờ, 30 chưa có giá**.
- Loader chạy bằng **đường dẫn script trực tiếp** trên DB mới: 30 pois, 5 restricted_zones, 900 travel_matrix.
- Ruff: **All checks passed**; regression mới nhất sau sửa503: **155 passed in41.75s**, không warning trong output lượt này.
  Sau sửa hết toolturns trước đó:147passed in41.83s.
  Sau sửa Gemini429 trước đó:138passed in51.51s.
  Bản đóng ZIP ban đầu:115pass; archive đó chưa chứa bản sửa Gemini/rate-limit.
- Web: `npm ci --ignore-scripts` thành công, audit 0 vulnerabilities tại thời điểm chạy;
  `npm run build` (tsc + Vite) thành công. Không coi build là kiểm thử thao tác giao diện bằng trình duyệt.
- `git diff --check` không có lỗi whitespace (chỉ cảnh báo Git LF→CRLF trên Windows).
- Không có make/gitleaks trong PATH: chạy trực tiếp tương đương make test, **chưa chạy gitleaks local**;
  cần CI/reviewer trước merge. Không sửa dependency để nâng phiên bản không cần thiết.
- Tests dùng LLM giả, HTTP mock, DB tạm: kiểm logic/orchestration, không đo được tỷ lệ reasoning LLM thật.

## Giới hạn phải nói với nhóm
1. UC-01 hội thoại/ask_user/interrupt là **Phase 2 chưa triển khai**. Phase 1 dùng form có sẵn.
2. Giá, min_age/walking/outdoor/visit-duration chưa có nguồn đủ: để NULL; không suy diễn miễn phí/an toàn/ít đi bộ.
   Hồ sơ trẻ/mobility chưa có metadata phù hợp có thể trả failed_validation. Cần bổ sung dữ liệu có nguồn,
   không xoá rule/chuyển NULL thành 0 để demo trông đẹp.
3. Nguồn OSM snapshot base 01/06/2026, đối chiếu 25/10; không phải dữ liệu thực địa cập nhật ngày hôm nay.
4. OSRM chỉ drive, không traffic/entrance đã xác minh; 3 điểm snap >100m (max ~334m).
   Không dùng để chỉ đường tới đúng cổng hoặc đảm bảo mọi tuyến tránh vùng cấm.
5. Vùng quân sự OSM là policy loại khỏi gợi ý, không xác nhận pháp lý; chưa kiểm hình học tuyến đường.
6. Tổng khoản biết giá không phải tổng trọn chuyến; mọi giá thiếu → total=NULL và cảnh báo.
7. Chưa chạy live OpenRouter/≥10 eval của nhóm, chưa có benchmark LLM 3 ngày hoặc bằng chứng ≥85% pass.
   Không dùng tokens/chi phí/latency fake làm số liệu báo cáo thật.
8. `TripProfile` chưa có destination, `Slot` chưa có mode; không tự sửa schema. Facade validator đọc DB;
   core `_with_facts` thuần. Cần lead duyệt cách tích hợp này và policy overload 4/6/8h, 3/6/10km.

## Checklist reviewer / giao bài
- P1: xem graph best-draft/history, repo total=NULL, unknown-POI, không đổi schema; phê duyệt policy/contract facts.
- P3: dùng ID canonical hiện có, kiểm bộ chấm riêng; không đưa đáp án eval vào runtime, không chỉnh test để giấu mismatch.
- P4: xem nhãn giá NULL và attribution UI; dùng mock weather normal/heavy_rain/timeout/abnormal khi demo.
- Khang: đọc `docs/uc-01.md`, `docs/uc-02.md`, `data/README.md`, AI disclosure; hôm sau ôn theo folder skill.
- Có archive source thì **giải nén vào thư mục mới**, không chép đè repo teammate có thay đổi chưa lưu.
- Nếu nhóm dùng branch: review `git status`/diff, chỉ stage file source/data/docs/tests liên quan; không stage `.env`, key,
  `.venv`, node_modules, DB hoặc traces. Sau khi Khang cho phép, commit/push `feat/P2-khang`, mở PR theo quy định nhóm.
  Không cần tạo lại nhánh. Lead vẫn phải review/CI, tag/video và eval chung không tự hoàn tất từ test P2.

## Các file chính
`scripts/{check_destination,load_destination,prepare_hue_data,build_travel_matrix}.py`,
`agent/src/tools/{destination,opening_hours}.py`, `agent/src/validation/{validator,facts}.py`,
`agent/src/nodes/plan.py`, `skills/itinerary-planning/SKILL.md`, `data/`, 4 test P2 mới + test loader,
và các thay đổi tích hợp nhỏ ở `agent/db/repo.py`, `agent/src/graph/app.py`, `web/src/App.tsx`, Makefile/README.

## Bổ sung khi Khang thử Google Gemini trực tiếp (25/10)
- Khang tự đổi `.env` và client theo hướng dẫn: `LLM_BASE_URL` Google OpenAI-compatible,
  `LLM_MODEL=gemini-3.5-flash-lite`, dùng key Google AI Studio riêng; **không đưa key vào tài liệu/Git**.
- Lần đầu HTTP500: backend chạy nhưng API POI lỗi, DB mặc định `tourguide.db` 0byte, chưa có bảng.
  Khang tạo/nạp DB mới rồi chạy dev trong cùng PowerShell có DB_PATH; xác nhận `/api/pois` hết lỗi.
  Không init lại DB chuyến đi cần giữ khi chỉ restart app.
- Log người dùng cung cấp sau đó cho thấy Gemini đã gọi tool thành công rồi gặp 429: quota ghi **15 request/phút**
  cho project/model free-tier trong thông báo đó. Một lượt lập lịch có nhiều LLM turns và nhiều vòng sửa,
  không phải 1 lần bấm = 1 API request; số bước trace cũng không phải số API request.
- Theo yêu cầu sửa trực tiếp, thêm `agent/src/graph/llm_requests.py` và dùng qua `agent_loop`:
  - Endpoint Google mặc định cách ít nhất 5 giây giữa thời điểm bắt đầu các HTTP attempt.
  - Limiter chung theo endpoint/model **trong cùng process**, dùng lock, không reset khi qua vòng replan/tạo client mới.
  - Có thể cấu hình `LLM_MIN_INTERVAL_SECONDS` (số hữu hạn 0..120); endpoint khác mặc định0.
  - 429: đọc Retry-After (giây/HTTP-date), retry-after-ms và Google RetryInfo.retryDelay (dict/list),
    thêm1giây biên; không có hint thì backoff15s/30s, tối đa **2 retry (3 HTTP attempts)**.
  - Hint yêu cầu chờ >60s hoặc hết lượt: dừng, giữ lỗi provider; không retry sớm hoặc đợi vô hạn.
  - Tắt retry ngầm SDK để wrapper kiểm soát số HTTP attempts. Ban đầu chỉ429; bản sửa503 bên dưới đã thêm5xx.
    Lỗi400/401 không retry ở wrapper.
  - Trace có `llm_wait`, `llm_retry`, `llm_retry_exhausted`, chỉ ghi thời gian/lý do, không key/payload.
- Không sửa `.env` hiện tại, schema, validator, số vòng replan hay dữ liệu để né quota.
- Đây không phải cách tăng/bỏ quota: project dùng chung, token/phút, ngày hoặc billing vẫn có thể gây429.
  Không xử lý limiter liên-process/máy khác; không tự bật billing/đổi key/project/model.
- 23 test chuyên biệt dùng HTTP mock + clock giả đã pass, gồm Google RetryInfo thực tế, header, cap/exhaustion,
  auth không retry, chia sẻ limiter qua client/replan/concurrency và tham số khoảng nghỉ sai.
  Full suite **138 passed in51.51s**, Ruff toàn repo pass, diff --check không lỗi whitespace.
- **ZIP source bàn giao ban đầu chưa chứa bản sửa Gemini/rate-limit này**. Không coi archive cũ là source mới nhất.

## Bổ sung: Gemini gọi tool tới hết15lượt (run r-55490cc7)
- Trace live người dùng gửi: vòng1 có bản nộp rồi validator trả lỗi giờ/overlap/travel; vòng2 đổi nhiều điểm,
  hỏi lại travel và giờ lần lượt, hết15turns. Đã đọc observation cụ thể: tool trả status=ok hoặc unknown hợp lệ,
  không phải key/quota hay tool mất kết nối trong run này.
- Sửa mà **không tăng15turns/max4round và không tắt validator**:
  - Trước vòng sửa, gom giờ/travel của bản trước qua tool; tái dùng observation thành công trong cùng run,
    không dùng lỗi/observation từ run khác, không coi unknown là cần retry.
  - Prompt/skill yêu cầu sửa tối thiểu slot lỗi, giữ slot đã đúng, gom tra cứu độc lập trong một lượt.
  - Feedback validator nêu chặng+minutes/mode thực, earliest start và khoảng giờ mở thay thông báo chung chung.
  - System nhắc ngân sách còn lại; hai lượt cuối dùng named tool_choice để yêu cầu submit_result,
    còn một lượt sửa nếu JSON/schema sai. Provider phớt lờ tool_choice vẫn dừng ở15, không loop vô hạn.
  - Hết lượt ở vòng sửa: graph giữ bản best đã qua schema/validator, kèm violations và cảnh báo;
    không tạo lịch thay LLM, không báo validated khi còn lỗi. Nếu vòng đầu chưa có draft thì vẫn báo lỗi rõ.
    Các RuntimeError khác không được bắt để giả thành thành công.
- Tests trong `tests/test_planner_turn_budget.py`, thêm test feedback cụ thể ở `test_p2_validator.py`;
  dùng LLM giả, không gọi Google. Cần Khang restart dev cùng PowerShell giữ DB_PATH rồi thử lại live.
  Full regression: **147passed in41.83s**, Ruff toàn repo All checks passed.
- Source tuần này đã triển khai nhưng **demo chạy ra bản failed_validation không đồng nghĩa đạt nghiệm thu**.
  Vẫn cần xem remaining violations, live demo đạt yêu cầu,10eval,review/CI trước khi chốt hoàn thành.

## Bổ sung: model quá tải503 (run r-a367af7c)
- Google báo model high demand/UNAVAILABLE, không phải key sai. User có draft vòng1 nhưng503 ở vòng sửa2.
- Wrapper hiện retry cả429 và5xx, cùng giới hạn2retry/3attempts; đọc Retry-After nếu có, không có thì15s/30s.
  Giữ giới hạn chờ60s, không đổi model, không gọi vô hạn hoặc bật thanh toán.
- Nếu vẫn lỗi429/5xx ở vòng sửa, giữ best đã kiểm cùng errors+noteHTTPstatus và tracekeep_best_on_provider_error.
  Nếu chưa có draft thì trả lỗi, không giả lịch; không nuốt401/400/lỗi code.
- Thêm8regression tests; full **155passed in41.75s**, Ruffpass, chỉ HTTPmock/LLMgiả.
  Chưa gọiGoogle thật để xác nhận hết503; user thử lại saurestart và đợi model bớt tải.
- Không thêm thư viện, schema hoặc biến cấu hình bắt buộc; sửa trong helper/graph hiện có, cầnP1review trướcmerge.
