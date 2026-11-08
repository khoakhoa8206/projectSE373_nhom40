# PWA: cài lên điện thoại

Trình duyệt chỉ cho **cài PWA** và **lấy vị trí** khi trang chạy qua **HTTPS** hoặc `localhost`. Mở bằng IP mạng LAN
(`http://192.168.x.x:5173`) thì app vẫn chạy nhưng không cài được và không có vị trí.

## Chuẩn bị trên máy tính

```bash
make dev                              # hoặc ít nhất: mock-weather :8081 + backend :8000
npm --prefix web run build && npm --prefix web run preview   # bản build có service worker, cổng 4173, /api proxy sang :8000
```

## Cách 1 · Android, cắm cáp USB (không cần mạng ngoài)

1. Điện thoại bật **Tuỳ chọn nhà phát triển → Gỡ lỗi USB**, cắm cáp vào máy tính.
2. Trên máy tính mở Chrome `chrome://inspect/#devices` → **Port forwarding** → thêm `4173` → `localhost:4173`, tick **Enable**.
3. Trên điện thoại mở Chrome `http://localhost:4173` → menu ⋮ → **Cài đặt ứng dụng** (hoặc **Thêm vào màn hình chính**).

Điện thoại coi đây là `localhost` nên cài được và lấy được vị trí.

## Cách 2 · iPhone hoặc Android không cáp: tunnel HTTPS tạm

1. Cài một lần: `winget install Cloudflare.cloudflared`.
2. `cloudflared tunnel --url http://localhost:4173` → in ra địa chỉ `https://<tên-ngẫu-nhiên>.trycloudflare.com`.
   `web/vite.config.ts` đã cho phép host `.trycloudflare.com` ở bản preview; host lạ khác vẫn bị chặn.
3. iPhone: Safari mở địa chỉ đó → nút Chia sẻ → **Thêm vào MH chính**. Android: Chrome → **Cài đặt ứng dụng**.

Địa chỉ tunnel là **công khai**: chỉ bật lúc thử hoặc demo, tắt ngay sau đó (Ctrl+C). App chỉ có 3 người dùng hư cấu, không có dữ liệu thật.

## Đã có trong PWA

| Hạng mục | Ở đâu |
|---|---|
| Manifest (tên, icon 192/512, `display: standalone`, màu chủ đạo) | `web/public/manifest.webmanifest`, `web/index.html` |
| Service worker: network-first cho file tĩnh, mất mạng thì mở khung app từ cache; `/api` và tile OSM luôn đi mạng | `web/public/sw.js` (chỉ đăng ký ở bản build) |
| Mất mạng: app vẫn mở, banner "Thiết bị đang mất mạng…" hiện ngay khi mất mạng, lỗi gọi API cũng báo mất mạng thay vì lỗi máy chủ | `web/src/App.tsx` (`OfflineBanner`), `web/src/api.ts` |
| Vị trí chỉ giữ trong phiên, có giải thích mục đích trước khi xin quyền | `web/src/location.ts` |

Kiểm tra (30/10/2026, Chrome qua DevTools Protocol trên bản preview): `Page.getInstallabilityErrors` = 0 lỗi, manifest 0 lỗi,
service worker điều khiển trang; ngắt mạng rồi tải lại vẫn mở được khung app.
