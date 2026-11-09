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

export type Question = { field: string; text: string };
export type ApprovalRequest =
  | { kind: "ask_user"; approval_id: string; data: { questions: Question[]; conflicts: string[] } }
  | { kind: "itinerary_approval"; approval_id: string; data: { itinerary_id: string } };
export type ApprovalAnswer = { decision: "approved" | "rejected" | "edited"; response: unknown };
export type ApprovalCardProps = {
  request: ApprovalRequest;
  busy: boolean;
  onAnswer: (answer: ApprovalAnswer) => Promise<void>;
};

/** P1 trả SSE theo hợp đồng; mất kết nối là lỗi, không được suy ra run đã xong. */
export function watchRun(runId: string, handlers: {
  onInterrupt: (request: ApprovalRequest) => void;
  onDone: (data: { message?: string; status?: string }) => void;
  onError: (message: string) => void;
}): () => void {
  const source = new EventSource(`/api/runs/${encodeURIComponent(runId)}/stream`);
  source.addEventListener("interrupt", (event) => {
    try {
      const request = JSON.parse((event as MessageEvent).data) as ApprovalRequest;
      if (!request.approval_id || !request.data || !["ask_user", "itinerary_approval"].includes(request.kind)) {
        throw new Error("Interrupt sai cấu trúc hoặc kind chưa hỗ trợ.");
      }
      if (request.kind === "ask_user" && (!Array.isArray(request.data.questions) || request.data.questions.length > 3
        || !request.data.questions.every((q) => typeof q.field === "string" && typeof q.text === "string")
        || !Array.isArray(request.data.conflicts) || !request.data.conflicts.every((item) => typeof item === "string"))) {
        throw new Error("Câu hỏi phải có field/text và tối đa 3 câu.");
      }
      if (request.kind === "itinerary_approval" && typeof request.data.itinerary_id !== "string") {
        throw new Error("Thiếu itinerary_id.");
      }
      handlers.onInterrupt(request);
    } catch {
      handlers.onError("Không đọc được interrupt từ backend.");
    }
    source.close();
  });
  source.addEventListener("done", (event) => {
    try {
      handlers.onDone(JSON.parse((event as MessageEvent).data));
    } catch {
      handlers.onError("Không đọc được trạng thái kết thúc.");
    }
    source.close();
  });
  source.addEventListener("error", (event) => {
    let message = "Mất kết nối SSE. Chưa thể xác nhận run đã xong; hãy kết nối lại, không gửi lại yêu cầu lập lịch.";
    if (event instanceof MessageEvent) {
      try { message = JSON.parse(event.data).message ?? message; } catch { /* giữ lỗi mạng */ }
    }
    source.close();
    handlers.onError(message);
  });
  return () => source.close();
}

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
    throw new ApiError(0, "Không kết nối được máy chủ. Kiểm tra mạng hoặc chạy `make dev`.");
  }
  const data = await res.json().catch(() => null);
  if (!res.ok) throw new ApiError(res.status, describe(res.status, data?.detail), data?.detail);
  return data as T;
}
