"""Kiểm thử end-to-end trên web thật bằng Playwright (Edge có sẵn trên Windows, không tải trình duyệt).

    pip install playwright            # không nằm trong requirements.txt: CI không chạy file này
    python run.py                     # terminal khác: app ở http://localhost:5173 (có LLM_API_KEY thì chạy agent thật)
    python scripts/e2e_smoke.py [--headed] [--out <thư mục ảnh>]

Luồng: VN/US → đăng ký (khung trượt) → lập lịch có vị trí hiện tại → rời trang (thanh chạy ngầm) → bản đồ đường thật →
duyệt → đánh dấu đã đi (nhật ký tự cập nhật) → sửa sau duyệt → từ chối bản sửa (giữ bản cũ) → thuyết minh điểm gần tôi.
Tạo 1 tài khoản e2e-*@example.com và xoá chuyến đi thử ở cuối. Vị trí giả lập ở Huế, không dùng vị trí thật."""

import argparse
import re
import secrets
import time
from pathlib import Path

from playwright.sync_api import Page, expect, sync_playwright

BASE = "http://localhost:5173"
HUE = {"latitude": 16.4690, "longitude": 107.5780}  # gần Đại Nội
AGENT_TIMEOUT = 25 * 60 * 1000  # LLM miễn phí trên OpenRouter: 1 lượt lập lịch có thể mất 5–15 phút


def step(name):
    print(f"[{time.strftime('%H:%M:%S')}] {name}", flush=True)


def wait_waiting_banner(page: Page):
    """Rời trang chuyến đi rồi chờ thanh báo chuyển sang 'đang chờ bạn' (agent chạy nền xong)."""
    page.goto(f"{BASE}/#/")
    banner = page.locator(".bg-runs")
    expect(banner).to_contain_text(re.compile("chờ bạn|gặp lỗi"), timeout=AGENT_TIMEOUT)
    assert "gặp lỗi" not in banner.inner_text(), "agent báo lỗi khi chạy nền: xem tab Trace của chuyến đi"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--headed", action="store_true")
    parser.add_argument("--out", type=Path, default=Path("e2e-shots"))
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    shot = lambda page, name: page.screenshot(path=args.out / f"{name}.png", full_page=False)
    errors = []

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=not args.headed)
        context = browser.new_context(viewport={"width": 1280, "height": 860}, geolocation=HUE, permissions=["geolocation"],
                                      locale="vi-VN")  # fmt: skip
        page = context.new_page()
        page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
        page.on("console", lambda m: m.type == "error" and errors.append(f"console: {m.text}"))

        step("1. Trang chủ + nút VN/US")
        page.goto(BASE)
        llm = page.request.get(f"{BASE}/api/ui/meta").json()["llm"]  # không có khoá LLM: planner giả, bỏ qua bước cần LLM
        skipped = []
        page.get_by_role("button", name="US").click()
        expect(page.locator(".nav-main")).to_contain_text("Explore")
        page.get_by_role("button", name="VN").click()
        expect(page.locator(".nav-main")).to_contain_text("Khám phá")

        step("2. Đăng ký qua khung trượt")
        page.locator(".top-row").get_by_role("button", name="Đăng nhập").click()
        shot(page, "02a-login")
        page.locator(".auth-panel.right button").click()
        expect(page.locator(".auth")).to_have_class(re.compile("signup"))
        page.wait_for_timeout(700)  # chờ hiệu ứng trượt
        shot(page, "02b-register")
        email = f"e2e-{secrets.token_hex(3)}@example.com"
        form = page.locator(".auth-form.register")
        form.locator("input[name=name]").fill("E2E Tester")
        form.locator("input[name=email]").fill(email)
        form.locator("input[name=password]").fill("matkhau-e2e-1")
        form.locator("input[name=confirm]").fill("matkhau-e2e-1")
        form.locator("button.primary").click()
        expect(page.locator(".account")).to_contain_text("E2E Tester")

        step("3. Lập lịch 1 ngày, dùng vị trí hiện tại làm điểm xuất phát")
        page.goto(f"{BASE}/#/plan")
        page.locator("input[type=date]").nth(1).fill("2026-11-25")
        page.locator("input[type=date]").nth(0).fill("2026-11-25")
        page.get_by_role("button", name="Lấy vị trí hiện tại").click()
        expect(page.locator(".here-bar")).to_contain_text("Gần")
        shot(page, "03-plan-location")
        page.locator("button[type=submit].wide.primary").click()
        page.wait_for_url(re.compile(r"#/trips/t-"), timeout=60_000)
        trip_url = page.url.split("?")[0]

        step("4. Rời trang khi agent đang chạy → thanh báo chạy ngầm")
        page.goto(f"{BASE}/#/")
        expect(page.locator(".bg-runs")).to_contain_text("chạy ngầm", timeout=20_000)
        shot(page, "04-background-banner")

        step("5. Chờ agent xong (chạy nền) rồi mở lại chuyến đi")
        wait_waiting_banner(page)
        page.locator(".bg-runs a").first.click()
        expect(page.locator("#approve")).to_be_visible(timeout=30_000)

        step("6. Bản đồ: đường đi thực tế (đường liền, nhiều điểm) + vị trí hiện tại")
        page.wait_for_function("""() => [...document.querySelectorAll('.leaflet-overlay-pane path')]
            .some(p => !p.getAttribute("stroke-dasharray") && (p.getAttribute("d") || "").length > 300)""", timeout=60_000)
        page.locator(".map-stick").get_by_role("button", name="Lấy vị trí hiện tại").click()
        expect(page.locator(".map-stick .here-bar")).to_contain_text("Gần bạn nhất trong lịch")
        shot(page, "06-route-and-location")

        step("7. Duyệt lịch trình (+ không lưu bộ nhớ nếu được hỏi)")
        page.locator("#approve").get_by_role("button", name="Duyệt", exact=True).click()
        skip_memory = page.get_by_role("button", name="Không lưu gì")
        visited = page.get_by_role("button", name="Đã đi", exact=True)
        expect(skip_memory.or_(visited).first).to_be_visible(timeout=120_000)  # 1 trong 2 hiện là được
        if skip_memory.is_visible():
            skip_memory.click()
        expect(visited.first).to_be_visible(timeout=60_000)

        step("8. Đánh dấu đã đi → nhật ký sự kiện cập nhật ngay, tóm tắt ngày tự chạy nền")
        visited.first.click()
        page.get_by_role("tab", name="Nhật ký").click()
        expect(page.locator(".event-log li").first).to_contain_text("Đã đi", timeout=15_000)
        if llm:
            expect(page.locator(".journal-day").first).to_be_visible(timeout=180_000)
        else:
            skipped.append("8b. tóm tắt nhật ký ngày tự chạy (cần LLM)")
        shot(page, "08-journal")

        step("9. Sửa lịch đã duyệt → chạy nền → từ chối bản sửa → giữ bản cũ")
        page.get_by_role("tab", name="Lịch trình").click()
        page.locator(".revise textarea").fill("Thêm nghỉ trưa 1 tiếng sau điểm đầu tiên")
        page.locator(".revise button.primary").click()
        expect(page.locator(".revise")).to_be_hidden(timeout=20_000)
        wait_waiting_banner(page)
        page.goto(trip_url)
        page.locator("#approve").get_by_role("button", name="Từ chối").click()
        expect(page.locator(".crumbs")).to_contain_text("Đã duyệt", timeout=60_000)
        expect(page.locator(".revise")).to_be_visible()
        shot(page, "09-kept-approved")

        step("10. Thuyết minh điểm gần tôi, trả lời đúng chế độ VN")
        page.goto(f"{BASE}/#/narrate")
        if llm:
            page.get_by_role("button", name="Tìm điểm gần tôi").click()
            page.get_by_role("button", name="Thuyết minh điểm này").click()
            answer = page.locator(".answer")
            expect(answer).to_be_visible(timeout=180_000)
            text = answer.inner_text()
            assert re.search(r"[ăâđêôơưạảấầẩẫậắằẳẵặẹẻẽếềểễệịỉọỏốồổỗộớờởỡợụủứừửữự]", text), "câu trả lời không phải tiếng Việt"
            shot(page, "10-narrate")
        else:
            skipped.append("10. thuyết minh (cần LLM)")

        step("11. Dọn: xoá chuyến đi thử, đăng xuất")
        page.goto(trip_url)
        page.get_by_role("button", name="Xoá dữ liệu chuyến đi").click()
        page.get_by_role("button", name="Xoá", exact=True).click()
        page.wait_for_url(re.compile(r"#/trips$"))
        page.get_by_role("button", name="Đăng xuất").click()
        browser.close()

    print(f"\nXONG. Tài khoản thử: {email}. Ảnh: {args.out.resolve()}")
    if skipped:
        print("Bỏ qua vì app chạy không có khoá LLM:\n  " + "\n  ".join(skipped))
    if errors:
        print("Lỗi trình duyệt ghi nhận:\n  " + "\n  ".join(errors))


if __name__ == "__main__":
    main()
