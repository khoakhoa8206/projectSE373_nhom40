"""Đo Recall@5 của retriever UC-03 trên evals/uc03/narration_qa.jsonl. Cần model thật nên chạy trên máy dev:
    python -m evals.uc03.recall               # in kết quả, lưu results/uc03-recall-<thời điểm>.json
    python -m evals.uc03.recall --write-readme  # ghi thêm số đo vào evals/uc03/README.md
Tạo DB tạm (schema + POI Huế) → ingest kho thật (dùng lại kb/index nếu nội dung không đổi) → top-5 cho từng câu.
Recall@5 = trung bình |gold ∩ top-5| / |gold| trên các câu có gold (khớp theo (doc_id, section)); Hit@5 = tỉ lệ câu có
ít nhất 1 gold trong top-5. Câu gold = [] (ngoài kho) không tính recall, chỉ ghi điểm top-1 để chọn ngưỡng out-of-KB."""

import argparse
import json
import os
import statistics
import tempfile
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

from agent.db import repo
from agent.db.init import init_db
from agent.src.rag import ingest as ing
from agent.src.rag import retriever
from scripts.check_destination import POI_PATH, check_pois

HERE = Path(__file__).resolve().parent
QA_PATH = HERE / "narration_qa.jsonl"
README = HERE / "README.md"
START, END = "<!-- recall:start -->", "<!-- recall:end -->"


def load_cases(path=QA_PATH) -> list[dict]:
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def retrieve(case, k=5) -> list[dict]:
    """Như cách node narrate gọi: có poi_id thì lọc tài liệu của POI trước, không có kết quả thì tìm toàn kho."""
    rows = retriever.search(case["question"], poi_id=case["poi_id"], k=k) if case.get("poi_id") else []
    return rows or retriever.search(case["question"], k=k)


def _stats(values, pick):
    return {"n": len(values), pick: round(max(values) if pick == "max" else min(values), 4),
            "median": round(statistics.median(values), 4)} if values else {"n": 0}


def evaluate(cases, k=5) -> dict:
    rows = []
    for case in cases:
        found = retrieve(case, k)
        top = [(r["doc_id"], r["section"]) for r in found]
        gold = [(g["doc_id"], g["section"]) for g in case["gold"]]
        hits = [item for item in gold if item in top]
        rows.append({"case_id": case["case_id"], "category": case.get("category", ""), "lang": case["lang"],
                     "question": case["question"], "in_kb": bool(gold),
                     "recall": len(hits) / len(gold) if gold else None, "hit": bool(hits) if gold else None,
                     "top1_score": round(found[0]["score"], 4) if found else None,
                     "top": [f"{d} §{s}" for d, s in top],
                     "missing": [f"{d} §{s}" for d, s in gold if (d, s) not in top]})  # fmt: skip
    in_kb = [r for r in rows if r["in_kb"]]
    by_category = {}
    for r in in_kb:
        by_category.setdefault(r["category"], []).append(r["recall"])
    summary = {
        "k": k, "cases": len(rows), "in_kb": len(in_kb), "out_of_kb": len(rows) - len(in_kb),
        "recall_at_k": round(statistics.fmean(r["recall"] for r in in_kb), 4) if in_kb else None,
        "hit_at_k": round(statistics.fmean(r["hit"] for r in in_kb), 4) if in_kb else None,
        "recall_by_category": {c: round(statistics.fmean(v), 4) for c, v in sorted(by_category.items())},
        "top1_in_kb": _stats([r["top1_score"] for r in in_kb if r["top1_score"] is not None], "min"),
        "top1_out_of_kb": _stats([r["top1_score"] for r in rows if not r["in_kb"] and r["top1_score"] is not None],
                                 "max"),
    }  # fmt: skip
    return {"summary": summary, "cases": rows}


def readme_block(result, info, measured_at) -> str:
    s = result["summary"]
    head = (f"Đo lúc {measured_at} · model `{info['model']}` · {info['documents']} tài liệu, {info['chunks']} chunk · "
            f"{s['in_kb']} câu có gold + {s['out_of_kb']} câu ngoài kho.")
    lines = [START, head, "",
             f"- **Recall@{s['k']} = {s['recall_at_k']}**, Hit@{s['k']} = {s['hit_at_k']}",
             "- Recall theo nhóm: " + ", ".join(f"{c} {v}" for c, v in s["recall_by_category"].items()),
             f"- Điểm top-1: câu có gold {s['top1_in_kb']}; câu ngoài kho {s['top1_out_of_kb']}", "",
             "Câu chưa lấy đủ gold trong top-5:", ""]  # fmt: skip
    misses = [r for r in result["cases"] if r["in_kb"] and r["recall"] < 1]
    lines += [f"- `{r['case_id']}` ({r['category']}) {r['question']} → thiếu {', '.join(r['missing'])}; top-1: "
              f"{r['top'][0] if r['top'] else '—'}" for r in misses] or ["- (không có)"]
    return "\n".join([*lines, END])


def write_readme(block, path=README):
    """Thay đoạn giữa 2 dấu recall:start/end trong README bằng số đo mới, giữ nguyên phần còn lại."""
    text = Path(path).read_text(encoding="utf-8")
    head, start, rest = text.partition(START)
    if not start or END not in rest:
        raise ValueError(f"{path} thiếu dấu {START} … {END}")
    Path(path).write_text(head + block + rest.partition(END)[2], encoding="utf-8")


def main():
    load_dotenv()
    ap = argparse.ArgumentParser(description="Đo Recall@5 của retriever UC-03 (cần model embedding thật)")
    ap.add_argument("--write-readme", action="store_true", help="ghi số đo vào evals/uc03/README.md")
    ap.add_argument("-k", type=int, default=5)
    args = ap.parse_args()
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        os.environ["DB_PATH"] = str(Path(tmp) / "recall.db")
        os.environ.setdefault("TRACE_DIR", str(Path(tmp) / "traces"))
        init_db()
        repo.save_hue_pois(check_pois(POI_PATH))
        info = ing.ingest()
        result = evaluate(load_cases(), args.k)
    measured_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    out = Path("results") / f"uc03-recall-{datetime.now():%Y%m%d-%H%M%S}.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(result | {"ingest": info, "measured_at": measured_at}, ensure_ascii=False, indent=1),
                   encoding="utf-8")  # fmt: skip
    block = readme_block(result, info, measured_at)
    print(block.replace(START, "").replace(END, "").strip(), f"\nChi tiết: {out}", sep="\n")
    if args.write_readme:
        write_readme(block)
        print(f"Đã ghi số đo vào {README}")


if __name__ == "__main__":
    main()
