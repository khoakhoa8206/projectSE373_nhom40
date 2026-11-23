// Vị trí: khoảng cách, điểm gần nhất, định dạng, nhận biết đang ở Huế. Không gọi mạng; transpile geo.ts như api.test.mjs.
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import ts from "typescript";

const source = await readFile(new URL("../src/geo.ts", import.meta.url), "utf8");
const { outputText } = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.ES2022, target: ts.ScriptTarget.ES2022 },
});
const { distanceM, nearestPoi, formatDistance, inHue } = await import(`data:text/javascript;base64,${Buffer.from(outputText).toString("base64")}`);

// Toạ độ POI lấy từ data/destinations/hue/poi.csv
const DAI_NOI = { poi_id: "hue-dai-noi", lat: 16.46955, lon: 107.57782 };
const THIEN_MU = { poi_id: "hue-chua-thien-mu", lat: 16.45355, lon: 107.54461 };
const HANOI = { lat: 21.0285, lon: 105.8542 };

test("điểm gần nhất và khoảng cách đường chim bay", () => {
  const nearDaiNoi = { lat: 16.468, lon: 107.58 };
  assert.equal(nearestPoi(nearDaiNoi, [THIEN_MU, DAI_NOI]).poi_id, "hue-dai-noi");
  assert.equal(nearestPoi(null, [DAI_NOI]), null);
  assert.equal(nearestPoi(nearDaiNoi, []), null);
  const km = distanceM(DAI_NOI, THIEN_MU) / 1000;
  assert.ok(km > 3.9 && km < 4.1, `Đại Nội → Thiên Mụ ≈ 4 km, ra ${km}`);
});

test("định dạng khoảng cách theo ngôn ngữ", () => {
  assert.equal(formatDistance(847, "vi"), "850 m");
  assert.equal(formatDistance(1234, "vi"), "1,2 km");
  assert.equal(formatDistance(1234, "en"), "1.2 km");
  assert.equal(formatDistance(629_123, "vi"), "629 km");
});

test("ở ngoài Huế thì không coi là đang ở Huế", () => {
  assert.equal(inHue(DAI_NOI), true);
  assert.equal(inHue(HANOI), false);
});
