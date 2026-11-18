import { useMemo, useState, type FormEvent } from "react";
import type { Poi } from "../api";
import type { Shell } from "../App";
import { getLang, t } from "../i18n";
import { Carousel, Empty, fold, go, PoiCard, Skeleton } from "../ui";

const CHIPS: [string, [string, string], (p: Poi) => boolean][] = [
  ["all", ["Tất cả", "All"], () => true],
  ["heritage", ["Di sản", "Heritage"], (p) => p.category === "attraction" && !p.poi_id.includes("chua")],
  ["pagoda", ["Chùa", "Pagodas"], (p) => p.poi_id.includes("chua")],
  ["food", ["Ẩm thực", "Food"], (p) => p.category === "food"],
  ["lodging", ["Lưu trú", "Stay"], (p) => p.category === "lodging"],
];
const EXAMPLES = () => getLang() === "en" ? [
  "Our family is visiting Hue for 3 days from 25/11/2026, 2 adults and a 6-year-old, about 8 million VND, we love food",
  "Hue for 2 days from 21/11/2026, 2 adults, relaxed pace",
] : [
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
        <img src="/poi/hero.jpg" alt={t("Sông Hương và cầu Trường Tiền nhìn từ trên cao", "Aerial view of the Perfume River and Truong Tien Bridge")} fetchPriority="high" />
        <div className="hero-copy wrap">
          <h1>{t("Khám phá Huế với thông tin có nguồn", "Explore Hue with sourced information")}</h1>
          <p>{t("Agent lập lịch theo ngày, kiểm tra giờ mở cửa và giá vé trước khi bạn duyệt.", "The agent plans day by day and checks opening hours and ticket prices before you approve.")}</p>
          <form className="search" onSubmit={search} role="search">
            <label htmlFor="q" className="sr">{t("Tìm địa điểm ở Huế", "Search places in Hue")}</label>
            <input id="q" value={typed} placeholder={t("Đại Nội, cơm hến, khách sạn...", "Imperial City, clam rice, hotel...")} onChange={(e) => { setTyped(e.target.value); if (!e.target.value) setQ(""); }} />
            <button className="primary">{t("Tìm", "Search")}</button>
          </form>
        </div>
      </section>

      <div className="wrap">
        <div className="chips" role="group" aria-label={t("Lọc theo loại", "Filter by type")}>
          {CHIPS.map(([id, label]) => <button key={id} className={chip === id ? "chip on" : "chip"} aria-pressed={chip === id} onClick={() => setChip(id)}>{t(...label)}</button>)}
        </div>

        {!pois.length && <Skeleton rows={4} />}
        {searching ? (
          <section className="results">
            <h2>{results.length} {t("địa điểm", results.length === 1 ? "place" : "places")}</h2>
            {results.length ? <div className="grid-cards">{results.map((p) => <PoiCard key={p.poi_id} poi={p} />)}</div>
              : <Empty title={t("Không tìm thấy địa điểm", "No places found")}><p className="muted">{t("Thử tên khác hoặc bỏ bộ lọc.", "Try another name or clear the filter.")}</p></Empty>}
          </section>
        ) : (
          <>
            <Carousel title={t("Không thể bỏ qua ở Cố đô", "Must-sees in the old capital")} sub={t("Có bài thuyết minh kèm trích dẫn", "With cited narration")} pois={pois.filter((p) => p.has_story && photo(p))} />
            <Carousel title={t("Chùa, lăng và di tích khác", "More pagodas, tombs and relics")} pois={pois.filter((p) => p.category === "attraction" && !p.has_story)} />

            <section className="planner-band">
              <img src="/poi/hue-cau-thanh-toan.jpg" alt={t("Cầu ngói Thanh Toàn", "Thanh Toan tiled bridge")} loading="lazy" />
              <form onSubmit={(e) => { e.preventDefault(); go(`/plan?text=${encodeURIComponent(story)}`); }}>
                <h2>{t("Kể chuyến đi, agent lên lịch", "Describe your trip, the agent plans it")}</h2>
                <label htmlFor="story">{t("Bạn muốn đi thế nào?", "How would you like to travel?")}</label>
                <textarea id="story" rows={4} value={story} onChange={(e) => setStory(e.target.value)} placeholder={t("Ngày đi, số người, ngân sách, sở thích", "Dates, group size, budget, interests")} />
                <div className="examples">
                  {EXAMPLES().map((x) => <button type="button" key={x} className="chip" onClick={() => setStory(x)}>{x.slice(0, 44)}...</button>)}
                </div>
                <button className="primary" disabled={story.trim().length < 3}>{t("Lập lịch trình", "Plan itinerary")}</button>
              </form>
            </section>

            <Carousel title={t("Ăn gì ở Huế", "What to eat in Hue")} sub={t("Giá chỉ hiện khi có nguồn", "Prices shown only when sourced")} pois={pois.filter((p) => p.category === "food")} />
            <Carousel title={t("Nghỉ đêm ở đâu", "Where to stay")} pois={pois.filter((p) => p.category === "lodging")} />

            <section className="trust">
              <h2>{t("Bạn luôn là người quyết định", "You always make the final call")}</h2>
              <dl>
                <div><dt>{t("Không đoán số liệu", "No guessed numbers")}</dt><dd>{t("Giờ và giá thiếu nguồn sẽ hiện nhãn chưa xác minh.", "Hours and prices without a source are labelled not verified.")}</dd></div>
                <div><dt>{t("Ba lớp kiểm tra", "Three layers of checks")}</dt><dd>{t("Validator, ba reviewer và bước kiểm chứng chạy trước khi trình bày.", "A validator, three reviewers and a fact-check step run before anything is shown.")}</dd></div>
                <div><dt>{t("Dữ liệu của bạn", "Your data")}</dt><dd>{t("Vị trí chỉ dùng trong phiên, bộ nhớ sở thích xem và xoá được.", "Location is used only for this session; saved preferences can be viewed and deleted.")}</dd></div>
              </dl>
            </section>
          </>
        )}
      </div>
    </>
  );
}
