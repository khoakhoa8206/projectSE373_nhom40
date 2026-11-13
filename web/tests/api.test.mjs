// Unit test transport với Fetch/EventSource giả; không gọi mạng hoặc LLM.
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import ts from "typescript";

const source = await readFile(new URL("../src/api.ts", import.meta.url), "utf8");
const { outputText } = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.ES2022, target: ts.ScriptTarget.ES2022 },
});
const { api, ApiError, watchRun } = await import(`data:text/javascript;base64,${Buffer.from(outputText).toString("base64")}`);

class FakeSource {
  static last;
  constructor(url) { this.url = url; this.handlers = {}; this.closed = false; FakeSource.last = this; }
  addEventListener(name, callback) { this.handlers[name] = callback; }
  emit(name, data) { this.handlers[name]({ data: JSON.stringify(data) }); }
  close() { this.closed = true; }
}

test("POST messages gửi text, không thêm user_id vào body", async () => {
  const original = globalThis.fetch;
  const requests = [];
  globalThis.fetch = async (url, options) => {
    requests.push({ url, options });
    return new Response(JSON.stringify({ run_id: "mock" }));
  };
  try {
    assert.deepEqual(await api("/trips/test/messages", { json: { text: "Yêu cầu hư cấu" } }), { run_id: "mock" });
    assert.equal(requests[0].options.method, "POST");
    assert.deepEqual(JSON.parse(requests[0].options.body), { text: "Yêu cầu hư cấu" });
  } finally { globalThis.fetch = original; }
});

test("Lỗi HTTP không trở thành thành công", async () => {
  const original = globalThis.fetch;
  globalThis.fetch = async () => new Response(JSON.stringify({ detail: "Không có API" }), { status: 404 });
  try { await assert.rejects(() => api("/missing"), (error) => error instanceof ApiError && error.status === 404); }
  finally { globalThis.fetch = original; }
});

test("SSE nhận interrupt và đóng kết nối, không tự duyệt", () => {
  const original = globalThis.EventSource;
  globalThis.EventSource = FakeSource;
  const received = [];
  try {
    watchRun("run/one", { onInterrupt: (value) => received.push(value),
      onDone: () => assert.fail("Không được tự done"), onError: () => assert.fail("Không được lỗi") });
    const request = { kind: "ask_user", approval_id: "ask-1", data: {
      questions: [{ field: "adults", text: "Có bao nhiêu người?" }], conflicts: [] } };
    FakeSource.last.emit("interrupt", request);
    assert.deepEqual(received, [request]);
    assert.equal(FakeSource.last.url, "/api/runs/run%2Fone/stream");
    assert.ok(FakeSource.last.closed);
  } finally { globalThis.EventSource = original; }
});

test("SSE hơn 3 câu hoặc thiếu field phải báo lỗi", () => {
  const original = globalThis.EventSource;
  globalThis.EventSource = FakeSource;
  const errors = [];
  try {
    for (const questions of [Array(4).fill({ field: "x", text: "x" }), [{ text: "Thiếu field" }]]) {
      watchRun("mock", { onInterrupt: () => assert.fail("Không nhận payload sai"),
        onDone: () => assert.fail(), onError: (message) => errors.push(message) });
      FakeSource.last.emit("interrupt", { kind: "ask_user", approval_id: "ask", data: { questions, conflicts: [] } });
      assert.ok(FakeSource.last.closed);
    }
    assert.equal(errors.length, 2);
  } finally { globalThis.EventSource = original; }
});

test("Mất SSE không coi run đã hoàn thành; cleanup đóng source", () => {
  const original = globalThis.EventSource;
  globalThis.EventSource = FakeSource;
  const errors = [];
  try {
    const close = watchRun("mock", { onInterrupt: () => assert.fail(), onDone: () => assert.fail(),
      onError: (message) => errors.push(message) });
    FakeSource.last.emit("error", {});
    assert.equal(errors.length, 1);
    assert.ok(FakeSource.last.closed);
    close();
  } finally { globalThis.EventSource = original; }
});
