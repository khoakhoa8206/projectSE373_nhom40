// W10-P4-3: nhãn ClaimBadge. Không gọi mạng; transpile claims.ts như api.test.mjs.
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import ts from "typescript";

const source = await readFile(new URL("../src/claims.ts", import.meta.url), "utf8");
const { outputText } = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.ES2022, target: ts.ScriptTarget.ES2022 },
});
const { claimView, sourceHost } = await import(`data:text/javascript;base64,${Buffer.from(outputText).toString("base64")}`);

const base = { claim_type: "price", claim_text: "150.000đ", source_url: "https://www.example.org/gia-ve", verified_at: "2026-11-09T10:00:00+07:00", corrected_text: null };

test("claim sai chỉ hiện giá trị đúng theo nguồn, không bao giờ hiện giá trị sai", () => {
  const v = claimView({ ...base, status: "contradicted", corrected_text: "200.000đ" }, "vi");
  assert.equal(v.tone, "fixed");
  assert.equal(v.label, "Giá: đã sửa theo nguồn");
  assert.equal(v.detail, "Giá trị theo nguồn: 200.000đ");
  assert.ok(!JSON.stringify(v).includes("150.000đ"));
});

test("đã xác minh có nguồn + ngày, chưa xác minh có lời nhắc", () => {
  const ok = claimView({ ...base, status: "verified" }, "en");
  assert.deepEqual([ok.tone, ok.label, ok.checkedOn], ["ok", "Price: verified", "2026-11-09"]);
  assert.deepEqual(ok.source, { url: base.source_url, host: "example.org", kind: "destination data" });
  const kb = claimView({ ...base, claim_type: "festival_date", status: "verified", evidence_kind: "kb" }, "vi");
  assert.equal(kb.source.kind, "kho tri thức");
  const unk = claimView({ ...base, status: "unverified", source_url: null, verified_at: null }, "vi");
  assert.deepEqual([unk.tone, unk.label, unk.source, unk.checkedOn], ["warn", "Giá: chưa xác minh", null, null]);
});

test("không tạo link cho URL lạ", () => {
  assert.equal(sourceHost("javascript:alert(1)"), null);
  assert.equal(sourceHost("không phải url"), null);
  assert.equal(sourceHost("http://127.0.0.1:8081/forecast?date=2026-11-27"), "127.0.0.1");
});
