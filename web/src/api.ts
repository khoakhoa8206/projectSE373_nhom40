// Kiểu dữ liệu = response của backend (agent/src/api/server.py, tên trường = cột DB).

export type User = { user_id: string; display_name: string; preferred_lang: "vi" | "en" };

export type PoiImage = { file: string; illustrative: boolean; title: string; author: string; license: string; license_url: string; source_url: string };

export type Poi = {
  poi_id: string; name_vi: string; name_en: string | null; category: "attraction" | "food" | "lodging"; lat: number; lon: number;
  opening_hours: string | null; ticket_price_vnd: number | null; source_url: string; license: string; verified_at: string;
  image: PoiImage | null; has_story?: boolean;
};

export type PoiDetail = Poi & {
  about: { lang: "vi" | "en"; title: string; section: string; text: string; doc_id: string; source_url: string; license: string }[];
  nearby: { poi_id: string; name_vi: string; name_en: string | null; category: string; minutes: number }[];
};

export type Claim = {
  claim_type: "opening_hours" | "price" | "festival_date" | "weather" | "distance"; claim_text: string; target_id?: string;
  status: "verified" | "unverified" | "contradicted"; source_url: string | null; verified_at: string | null; corrected_text: string | null;
};

export type Finding = { slot_ref: string | null; severity: "low" | "medium" | "high"; rule: string; message: string; suggestion: string | null };
export type Report = { report_id: number; round: number; reviewer: "local_expert" | "budget" | "safety"; verdict: "approve" | "request_changes"; findings: Finding[] };
export type TripEvent = { event_id: string; day_index: number; event_type: string; slot_id: string | null; amount_vnd: number | null; payload: string };
export type Journal = { scope: "day" | "trip"; day_index: number | null; lang: "vi" | "en"; content: { summary: string; highlights: { text: string }[] }; event_ids: string[]; total_spent_vnd: number; tokens_before: number | null; tokens_after: number | null; run_id: string };
export type RunRow = { run_id: string; uc: string; status: string; started_at: string; latency_ms: number | null; tokens_in: number; tokens_out: number };

export type TripDetail = {
  trip: { trip_id: string; status: string };
  profile: (TripProfile & { hard_constraints: string[]; route: string }) | null;
  pending: InterruptPayload | null;
  itinerary: Itinerary | null;
  claims: Claim[];
  review: { reports: Report[]; coordination: { ts: string; from: string; to: string; message: string }[] };
  events: TripEvent[];
  journal: Journal[];
  runs: RunRow[];
  running: boolean;
};

export type TripRow = { trip_id: string; status: string; start_date: string | null; end_date: string | null; request: string | null; waiting: number | null; adults: number | null; budget_total_vnd: number | null };
export type MemoryRow = { memory_id: string; kind: string; value: string; sensitivity: "normal" | "sensitive"; created_at: string; expires_at: string };
export type Citation = { doc_id: string; section: string; source_url: string; quote: string };
export type Narration = { text: string; citations: Citation[]; out_of_kb: boolean; run_id: string };

export type TripProfile = {
  start_date: string;
  end_date: string;
  adults: number;
  children: { age: number }[];
  budget_total_vnd: number | null;
  interests: string[];
  pace: "relaxed" | "moderate" | "packed" | null;
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
  progress?: "planned" | "done" | "skipped";
  cost_source: "tool" | "unverified" | "free";
  hours_status: "verified" | "unverified" | "not_applicable";
  note: string | null;
  name_vi: string | null;
  name_en?: string | null;
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
  | { kind: "itinerary_approval"; approval_id: string; data: { itinerary_id: string } }
  | { kind: "memory_save"; approval_id: string; data: { items: MemoryItem[] } };
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
      if (!request.approval_id || !request.data || !["ask_user", "itinerary_approval", "memory_save"].includes(request.kind)) {
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
  if (status === 401) return typeof detail === "string" ? detail : "Bạn cần đăng nhập.";
  if (Array.isArray(detail)) return "Hồ sơ chưa hợp lệ: " + detail.map((d) => `${d.loc.slice(1).join(".")}: ${d.msg}`).join("; ");
  if (typeof detail === "string") return detail;
  if (detail?.error) return `Agent gặp lỗi: ${detail.error}`;
  return `Máy chủ lỗi (HTTP ${status}): backend chưa chạy hoặc gặp lỗi, xem log ở terminal chạy backend.`;
}

/** Gọi /api/<path>. Có `json` thì POST. Lỗi nào cũng thành ApiError với thông báo tiếng Việt đọc được. */
export async function api<T>(path: string, init?: { method?: "POST" | "PATCH" | "DELETE"; json?: unknown }): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`/api${path}`, {
      method: init?.method ?? (init ? "POST" : "GET"),
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
  name?: string | null; // SSE của P1 đặt tên tool ở name
  duration_ms?: number;
  payload?: unknown;
};

/** POST /api/trips/{trip_id}/resume: graph chạy tiếp từ điểm dừng, trả run_id mới để mở stream. */
export function resume(tripId: string, body: { approval_id: string; decision: Decision; response: unknown }) {
  return api<{ run_id: string }>(`/trips/${tripId}/resume?background=true`, { json: body });
}

// Trang Memory.tsx cũ (P1) vẫn dùng; giao diện mới dùng MemoryRow.
export type SavedMemory = {
  memory_id: string;
  kind: "food_like" | "food_dislike" | "allergy" | "dietary" | "pace" | "interest" | "visited_city" | "other";
  value: string;
  sensitivity: "normal" | "sensitive";
  source_trip_id: string | null;
  created_at: string;
  expires_at: string;
};

export type MemoryList = { items: SavedMemory[]; sensitive_consent: boolean };
