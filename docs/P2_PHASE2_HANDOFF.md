# Bàn giao Phase 2 P2 · 09/11/2026

Phạm vi duy nhất: `C:\Users\NGO HOANG KHANG\Downloads\P2_EnnKhang.md`.
Không coi unit test/mock/screenshot là kết quả LLM thật hoặc nghiệm thu tích hợp.

## Hiện hành: UC-01 pass23case và đã có3mẫuliveUC-02

- User tự chạy, evidence `results/uc01-20261109-214953/cases.jsonl` đã được đối chiếu local:
  **23/23 PASS**, 23 run succeeded; schema23/23, hard fields90/90, conflict5/5, unsupported3/3,
  tương ứng100% từng metric; missing metrics0. Không cần chạy lại UC-01 ngay.
- Đây là metric của bộ case/lượt chạy này, không thay cho nghiệm thu API/checkpointer/PWA hoặc cả6ticket.
  Vẫn giữ kết quả lần đầu và ghi hạn chế ở `docs/uc-01.md` mục10–11.
- Git kiểm theo đường dẫn: `.env`, results và DB lần chạy mới bị ignore, không tracked;
  chỉ `.env.example` được tracked. Đây không phải kết quả quét secrets toàn lịch sử.
- Chưa push/PR/merge. Nhánh hiện tại vẫn là `feat/W8-P2-1-fix`, kế thừa stack cũ.
- User đã tạo3JSONliveUC-02, evidence `results/phase2-examples-ecde847e`; schema test2pass0.98s.
  Hai mẫu validated (2/1vòng); low-budget failed_validation sau4vòng vì overlap6phút di chuyển,
  không sửa trạng thái hoặc chạy lại để giấu lỗi. Tất cả chưa được duyệt và có khoản thiếu giá.
  Chi tiết ở `docs/uc-02.md` mục11. Không cần gọi Gemini thêm chỉ để ghi đè bản này.
- Sau khi cóartifact, regression offline mới nhất: **294 passed in 44.23s**, không skip, Ruff pass.
  Test dùng dotenvdisabled/cấu hìnhLLMgiả riêng, không sửa.env hoặc gọi provider.
- Việc tiếp theo còn thiếu trong P2: phối hợp P1/P4, chuẩn bị diff/PR đúngticket, báo rõ mẫu còn lỗi.
  Các mốc “chưa có artifact/chưa chạy lại” phía dưới là lịch sử.

## Cập nhật sau lần eval live đầu tiên

- User đã cấu hình Gemini và tự chạy UC-01. Evidence `results/uc01-20261109-213211`:
  **18/23 pass**, schema 95,65%, hard accuracy 91,11%, conflict 80%, unsupported 100%, missing metrics 0.
  Chưa đạt đủ mục tiêu; giữ nguyên evidence, không sửa gold/scorer.
- I11 là `APIConnectionError`, không phải lỗi nội dung được chứng minh. I09 vẫn giữ các ý ràng buộc
  trong trace, chưa thể khẳng định do mất dữ kiện; cần review cách biểu diễn/chấm.
- Nhánh sửa intake hiện tại **`feat/W8-P2-1-fix`** được tách từ HEAD UI để không thay đổi các nhánh đã lưu.
  Nhánh này vẫn kế thừa stack cũ; commit sửa chỉ thuộc W8-P2-1, không phải một PR độc lập vào main.
- Sửa code xác nhận cả khoảng ngày khi mâu thuẫn số ngày; skill phân biệt một ngày và chỉ khởi hành,
  nhắc tách từng ràng buộc. Thêm 8 test giả; chưa có kết quả Gemini sau sửa, không cam kết các case sẽ pass.
- Offline sau sửa: Ruff pass, intake26pass; full **293 passed, 1 skipped in 87.55s** với dotenv tắt
  và cấu hình LLM giả trong tiến trình test. Lượt full trực tiếp đầu timeout120s, không tính như pass.
- Bước tiếp: user tự chạy lại `python -m evals.run --uc UC-01` (có thể dùng quota/phí);
  sau đó tổng hợp report trên folder **mới**, không ghi đè hay gộp thành tỷ lệ của lần đầu.
  Chưa push/PR/merge; 3JSONlive và tích hợp P1/P4 vẫn chưa hoàn tất.

## Đúng thư mục và cách tách ticket

- Clone gốc: `D:\SE373_Agentic-ai_tourguide_hue\nhom-40`, đang giữ nhánh W8-P2-2.
- Worktree có các bổ sung tiếp theo: **`D:\SE373_Agentic-ai_tourguide_hue\nhom-40-p2-work`**,
  hiện nhánh `feat/W8-P2-1-fix` (bao gồm UI). Các file intake/eval/UI mới nằm ở đây, không phải bị mất khỏi clone gốc.
- User cho phép commit/nhánh local; không push, tạo PR hoặc merge. Không fetch/pull main nên không biết trạng thái remote mới nhất.
- Chuỗi local: `W8-P2-2 → W8-P2-1 → W9-P2-1 → W9-P2-2 → W9-P2-3`.
  Đây là **stacked branches**: mỗi commit chỉ làm ticket tương ứng, nhưng nhánh sau kế thừa commit trước.
  Khi mở PR, dùng nhánh trước làm base tạm hoặc đợi lead merge tiền nhiệm rồi cập nhật base;
  không mở tất cả vào main cùng lúc rồi coi diff gộp là một-ticket-một-PR.
- `feat/W8-P2-3` là nhánh độc lập đã có commit79d1f31. Manifest v1 và nguồn mùa lũ cùng đường dẫn:
  khi ghép PR phải giữ cả inventory và policy, cập nhật hashpoi; không tự chọn bỏ một bên.

## Trạng thái từng nhiệm vụ

| Ticket | Đã code/kiểm local | Còn thiếu để nghiệm thu |
|---|---|---|
| W8-P2-3 | Manifest5file, checker/tests trên nhánh riêng79d1f31; user báo168tests pass | Lead review/merge; ghép nguồn policy/hashpoi mới khi tích hợp |
| W8-P2-2 | Tool/registry, 6rule có test, mùa lũ/tag có nguồn; commit6e1320a,229tests pass | Review/CI; timeoutSQLite không phải hard deadline geometry |
| W8-P2-1 | IntakeResult cục bộ, route/conflicts, ≤3câu, schema≤2lầnsửa, version; commit462b00b,247tests pass | API/checkpointer/interrupt P1, nghiệm thu restart end-to-end |
| W9-P2-1 | Node approve, graph factory, repo helper,≤4vòng,fallback; đã có3JSONlive qua schema test,2validated/1failed_validation | P1 nối API/checkpointer; review mẫu low-budget còn overlap, không coi tất cả lịch đã hợp lệ |
| W9-P2-2 | 23case, scorer/metrics, plug-in runner,29tests evaluator; user chạy live23/23PASS, bốnmetric100% sau sửa intake | Chuyển transport sang resume thật khi API P1 có; đưa tổng hợp vào README khi chuẩn bị PR |
| W9-P2-3 | Chat/SSE/resume client, tabngày/map/nhãn, giữ Nhập nhanh; adapter P2 tạm và5transporttests | Thay adapter bằng ApprovalCard P4; P1 endpoints; kiểm PWA/điện thoại + demo thật |

## Bằng chứng local cuối phiên

- Python: **285 passed, 1 skipped in 46.08s**. Skip là 3 artifact live chưa có, không phải lỗi bị giấu.
- Ruff: All checks passed.
- Frontend: `npm test` **5/5 pass** bằng Fetch/EventSource giả; `npm run build` pass (tsc + Vite).
- Browser kiểm iframe rộng390px: hỏi adults → gửi answer → interrupt duyệt → render lịch giả;
  đúng nhãn giờ/giá/tổng thiếu, vi phạm còn lại, 2tabngày/2pathLeaflet; không tràn ngang (scrollWidth375<innerWidth390).
  Browser relay không gửi được POST local (502/emptyresponse), nên phần POST trong browser được mock bằng Fetch;
  không coi đây là kiểm HTTP/API thật. Mock API POST trực tiếp PowerShell trả thành công.
- Ảnh `docs/screenshots/phase2-ui-mock-mobile.png`: Chrome headless chụp iframe390px, dữ liệu hư cấu có nhãn rõ.
  Không phải ảnh điện thoại thật hoặc lịch sinh bởi LLM.
- Không đổi `schema.sql`/`agent/schemas`; không viết API/checkpointer P1 hoặc tự tạo component mang tên ApprovalCard P4.
- File chung chạm có lý do cần review: `app.py` (registry/factory), `repo.py` (thêm2helper),
  `evals/run.py` (hook plug-in), `App.tsx/api.ts` (UI/contract), giữ public signatures cũ.

## Lệnh user chạy LLM thật sau khi có key

Không gửi key cho trợ lý hoặc commit `.env`. `.venv` dùng chung ở clone gốc, `.env` của worktree không được Git sao chép.
User tự cấu hình LLM_API_KEY/LLM_BASE_URL/LLM_MODEL trong môi trường hoặc .env riêng tại worktree.

```powershell
cd 'D:\SE373_Agentic-ai_tourguide_hue\nhom-40-p2-work'
$py = 'D:\SE373_Agentic-ai_tourguide_hue\nhom-40\.venv\Scripts\python.exe'
# UC-01: gọi provider thật, tạo DB/evidence mới trong results/.
& $py -X utf8 -m evals.run --uc UC-01
# Tổng hợp: thay ... bằng folder thật vừa chạy; ghi số thực vào evals/uc01/README.md.
# & $py -X utf8 -m evals.uc01.report results/uc01-.../cases.jsonl
```

3 mẫu UC-02 cần mock-weather riêng (terminal1), không có dữ kiện thời tiết thật:

```powershell
& 'D:\SE373_Agentic-ai_tourguide_hue\nhom-40\.venv\Scripts\python.exe' -X utf8 -m uvicorn mocks.mock_weather.app:app --port 8081
```

Terminal2 trong cùng worktree (sau khi thiết lập key):

```powershell
& 'D:\SE373_Agentic-ai_tourguide_hue\nhom-40\.venv\Scripts\python.exe' -X utf8 -m scripts.export_phase2_examples --live
& 'D:\SE373_Agentic-ai_tourguide_hue\nhom-40\.venv\Scripts\python.exe' -X utf8 -m pytest tests/test_phase2_examples.py -q
```

Script tạo DB/evidence UUID mới trong results/, không nạp lại DB chuyến đi thật và từ chối ghi đè file mẫu.
Giữ failed_validation nếu thực tế còn lỗi; không sửa thành approved/validated để đẹp demo.
BaJSON sinh ra thuộc W9-P2-1: cập nhật nhánh đó bằng quy trình user/lead chọn, không vô tình commit vào ticketUI.

## Phối hợp tối thiểu với nhóm

- P1: nhận `intake(state, client, usage)`/route_intake và `build_approval_graph(..., checkpointer)`;
  hoàn thiện server messages/resume/SSE theo hợp đồng, ownership/concurrency/checkpointer bền vững.
  Khi ask_user response là map field→text, cần lưu nội dung trả lời thành message trước khi gọi lại intake.
- P4: cấp ApprovalCard; `ProfilePage` nhận component qua prop ApprovalCard với interface ghi ở api.ts.
  Adapter tạm được đặt tên khác, không ghi đè component nhóm.
- Kịch bản demo: chat thiếu số người → hỏi≤3câu → trả lời → lập lịch → duyệt/sửa;
  kiểm max4vòng, nhãn thiếu giá/giờ, vi phạm, đường nối không phải tuyến thật;
  tắt/bật backend trong lúc chờ chỉ sau khi P1 cung cấp persistent checkpointer. Clip chưa quay.

**Chưa push/PR/CI/merge, chưa chạy LLM thật. Không báo cả6ticket đã nghiệm thu.**
