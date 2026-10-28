// Kiểu dữ liệu = response của backend (agent/src/api/server.py, tên trường = cột DB).

export type User = { user_id: string; display_name: string; preferred_lang: "vi" | "en" };

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public detail?: unknown,
  ) {
    super(message);
  }
}

type Detail = string | { loc: (string | number)[]; msg: string }[] | { error?: string; run_id?: string } | undefined;

function describe(status: number, detail: Detail): string {
  if (status === 401) return "Phiên đã hết, hãy chọn lại người dùng.";
  if (Array.isArray(detail)) return "Hồ sơ chưa hợp lệ: " + detail.map((d) => `${d.loc.slice(1).join(".")}: ${d.msg}`).join("; ");
  if (typeof detail === "string") return detail;
  if (detail?.error) return `Agent gặp lỗi: ${detail.error}`;
  return `Máy chủ lỗi (HTTP ${status}): backend chưa chạy hoặc gặp lỗi, xem log ở terminal chạy backend.`;
}

/** Gọi /api/<path>. Có `json` thì POST. Lỗi nào cũng thành ApiError với thông báo tiếng Việt đọc được. */
export async function api<T>(path: string, init?: { method?: "POST"; json?: unknown }): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`/api${path}`, {
      method: init ? "POST" : "GET",
      headers: init?.json === undefined ? undefined : { "Content-Type": "application/json" },
      body: init?.json === undefined ? undefined : JSON.stringify(init.json),
    });
  } catch {
    throw new ApiError(0, "Không kết nối được máy chủ. Kiểm tra mạng hoặc chạy `make dev`.");
  }
  const data = await res.json().catch(() => null);
  if (!res.ok) throw new ApiError(res.status, describe(res.status, data?.detail), data?.detail);
  return data as T;
}
