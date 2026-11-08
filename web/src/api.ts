// Kiểu dữ liệu = response của backend (agent/src/api/server.py, tên trường = cột DB).

export type User = { user_id: string; display_name: string; preferred_lang: "vi" | "en" };

export type Poi = { poi_id: string; name_vi: string; category: "attraction" | "food" | "lodging"; lat: number; lon: number };

export type TripProfile = {
  start_date: string;
  end_date: string;
  adults: number;
  children: { age: number }[];
  budget_total_vnd: number | null;
  interests: string[];
  pace: "relaxed" | "moderate" | "packed";
  language: "vi" | "en";
  mobility_notes: string | null;
};

export type Slot = {
  slot_id: string;
  day_index: number;
  slot_date: string;
  start_time: string;
  end_time: string;
  poi_id: string | null;
  activity: string;
  travel_minutes_from_prev: number | null;
  cost_vnd: number | null;
  cost_source: "tool" | "unverified" | "free";
  hours_status: "verified" | "unverified" | "not_applicable";
  note: string | null;
  name_vi: string | null;
  lat: number | null;
  lon: number | null;
};

export type Itinerary = {
  itinerary_id: string;
  status: string;
  planner_rounds: number;
  total_cost_vnd: number | null;
  has_unpriced_item: number;
  slots: Slot[];
  violations: { violation_id: number; slot_id: string | null; rule: string; severity: string; message: string }[];
};

export type PlanResult = { run_id: string; itinerary_id: string | null; status: string; error: string | null };

export type TraceEvent = {
  seq: number;
  node: string;
  kind: string;
  name: string | null;
  args: unknown;
  result: unknown;
  duration_ms: number | null;
  tokens: number | null;
  error: string | null;
};

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
    // PWA mở được khi mất mạng (service worker cache khung app) nhưng agent, lịch trình, bản đồ vẫn cần mạng
    throw new ApiError(0, navigator.onLine
      ? "Không kết nối được máy chủ. Kiểm tra mạng hoặc chạy `make dev`."
      : "Thiết bị đang mất mạng. Agent và lịch trình cần mạng, hãy bật mạng rồi thử lại.");
  }
  const data = await res.json().catch(() => null);
  if (!res.ok) throw new ApiError(res.status, describe(res.status, data?.detail), data?.detail);
  return data as T;
}

// ---- Hợp đồng chung với P1: interrupt (thread_id = trip_id), resume, SSE tiến trình ----

export type MemoryItem = { key: string; value: string; sensitivity: "normal" | "sensitive" };

/** payload của interrupt(): graph dừng chờ người dùng. */
export type InterruptPayload =
  | { kind: "ask_user"; approval_id: string; data: { questions: { field: string; text: string }[]; conflicts?: unknown[] } }
  | { kind: "itinerary_approval"; approval_id: string; data: { itinerary_id: string } }
  | { kind: "memory_save"; approval_id: string; data: { items: MemoryItem[] } };

export type Decision = "approved" | "rejected" | "edited";

/** 1 sự kiện của GET /api/runs/{run_id}/stream; `kind` = tên `event:` của SSE. Toạ độ đã che còn 2 số thập phân. */
export type StreamEvent = {
  kind: "node_start" | "node_end" | "tool_call" | "interrupt" | "done" | "error";
  run_id: string;
  node: string;
  ts: string;
  tool?: string;
  duration_ms?: number;
  payload?: unknown;
};

/** POST /api/trips/{trip_id}/resume: graph chạy tiếp từ điểm dừng, trả run_id mới để mở stream. */
export function resume(tripId: string, body: { approval_id: string; decision: Decision; response: unknown }) {
  return api<{ run_id: string }>(`/trips/${tripId}/resume`, { json: body });
}
