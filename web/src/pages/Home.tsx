import { useMemo, useState, type FormEvent } from "react";
import type { Poi } from "../api";
import type { Shell } from "../App";
import { Carousel, Empty, fold, go, PoiCard, Skeleton } from "../ui";

const CHIPS: [string, string, (p: Poi) => boolean][] = [
  ["all", "Tất cả", () => true],
  ["heritage", "Di sản", (p) => p.category === "attraction" && !p.poi_id.includes("chua")],
  ["pagoda", "Chùa", (p) => p.poi_id.includes("chua")],
  ["food", "Ẩm thực", (p) => p.category === "food"],
  ["lodging", "Lưu trú", (p) => p.category === "lodging"],
];
const EXAMPLES = [
  "Nhà mình đi Huế 3 ngày từ 25/11/2026, 2 người lớn 1 bé 6 tuổi, khoảng 8 triệu, thích ăn uống",
  "Đi Huế 2 ngày từ 21/11/2026, 2 người lớn, đi thong thả",
];

export default function Home({ shell }: { shell: Shell }) {
  const { pois } = shell;
  const [q, setQ] = useState("");
  const [typed, setTyped] = useState("");
  const [chip, setChip] = useState("all");
  const [story, setStory] = useState("");

  const results = useMemo(() => {
    const test = CHIPS.find((c) => c[0] === chip)![2];
    const needle = fold(q.trim());
    return pois.filter((p) => test(p) && (!needle || fold(`${p.name_vi} ${p.name_en ?? ""}`).includes(needle)));
  }, [pois, q, chip]);

  const searching = q.trim() !== "" || chip !== "all";
  const photo = (p: Poi) => !!p.image && !p.image.illustrative;
  function search(e: FormEvent) {
    e.preventDefault();
    setQ(typed);
  }

  return (
    <>
      <section className="hero">
        <img src="/poi/hero.jpg" alt="Sông Hương và cầu Trường Tiền nhìn từ trên cao" fetchPriority="high" />
        <div className="hero-copy wrap">
          <h1>Khám phá Huế với thông tin có nguồn</h1>
          <p>Agent lập lịch theo ngày, kiểm tra giờ mở cửa và giá vé trước khi bạn duyệt.</p>
          <form className="search" onSubmit={search} role="search">
            <label htmlFor="q" className="sr">Tìm địa điểm ở Huế</label>
            <input id="q" value={typed} placeholder="Đại Nội, cơm hến, khách sạn..." onChange={(e) => { setTyped(e.target.value); if (!e.target.value) setQ(""); }} />
            <button className="primary">Tìm</button>
          </form>
        </div>
      </section>

      <div className="wrap">
        <div className="chips" role="group" aria-label="Lọc theo loại">
          {CHIPS.map(([id, label]) => <button key={id} className={chip === id ? "chip on" : "chip"} aria-pressed={chip === id} onClick={() => setChip(id)}>{label}</button>)}
        </div>

        {!pois.length && <Skeleton rows={4} />}
        {searching ? (
          <section className="results">
            <h2>{results.length} địa điểm</h2>
            {results.length ? <div className="grid-cards">{results.map((p) => <PoiCard key={p.poi_id} poi={p} />)}</div>
              : <Empty title="Không tìm thấy địa điểm"><p className="muted">Thử tên khác hoặc bỏ bộ lọc.</p></Empty>}
          </section>
        ) : (
          <>
            <Carousel title="Không thể bỏ qua ở Cố đô" sub="Có bài thuyết minh kèm trích dẫn" pois={pois.filter((p) => p.has_story && photo(p))} />
            <Carousel title="Chùa, lăng và di tích khác" pois={pois.filter((p) => p.category === "attraction" && !p.has_story)} />

            <section className="planner-band">
              <img src="/poi/hue-cau-thanh-toan.jpg" alt="Cầu ngói Thanh Toàn" loading="lazy" />
              <form onSubmit={(e) => { e.preventDefault(); go(`/plan?text=${encodeURIComponent(story)}`); }}>
                <h2>Kể chuyến đi, agent lên lịch</h2>
                <label htmlFor="story">Bạn muốn đi thế nào?</label>
                <textarea id="story" rows={4} value={story} onChange={(e) => setStory(e.target.value)} placeholder="Ngày đi, số người, ngân sách, sở thích" />
                <div className="examples">
                  {EXAMPLES.map((x) => <button type="button" key={x} className="chip" onClick={() => setStory(x)}>{x.slice(0, 44)}...</button>)}
                </div>
                <button className="primary" disabled={story.trim().length < 3}>Lập lịch trình</button>
              </form>
            </section>

            <Carousel title="Ăn gì ở Huế" sub="Giá chỉ hiện khi có nguồn" pois={pois.filter((p) => p.category === "food")} />
            <Carousel title="Nghỉ đêm ở đâu" pois={pois.filter((p) => p.category === "lodging")} />

            <section className="trust">
              <h2>Bạn luôn là người quyết định</h2>
              <dl>
                <div><dt>Không đoán số liệu</dt><dd>Giờ và giá thiếu nguồn sẽ hiện nhãn chưa xác minh.</dd></div>
                <div><dt>Ba lớp kiểm tra</dt><dd>Validator, ba reviewer và bước kiểm chứng chạy trước khi trình bày.</dd></div>
                <div><dt>Dữ liệu của bạn</dt><dd>Vị trí chỉ dùng trong phiên, bộ nhớ sở thích xem và xoá được.</dd></div>
              </dl>
            </section>
          </>
        )}
      </div>
    </>
  );
}
