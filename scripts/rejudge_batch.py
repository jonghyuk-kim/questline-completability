"""저장된 출력 원문을 지금의 파서와 검사기로 다시 판정하고 채점한다.

    .venv/bin/python scripts/rejudge_batch.py runs/questline/<배치> --lines scenarios/questlines_pre.yaml

검사기나 파서의 오탐을 고친 뒤 이미 돈 배치에 적용할 때 쓴다. 모델은 다시 부르지 않는다. 처음 판정은
cells.before_rejudge.jsonl, scores.before_rejudge.jsonl 로 한 번만 보관한다(이미 있으면 덮어쓰지 않는다).
C2 는 바뀐 판정이 피드백 문장과 재생성 여부를 바꿀 수 있어, 다시 판정해도 실제로 돌렸을 경로와 같다는 보장이 없다.
그래서 C2 셀의 판정이 바뀌면 경고를 찍는다 - 그 셀은 다시 돌릴지 연구자와 정한다.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from questline.checker import Index  # noqa: E402
from questline.lines import load_lines  # noqa: E402
from questline.run import judge  # noqa: E402
from questline.score import score_cell  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("batch")
    ap.add_argument("--lines", required=True)
    ap.add_argument("--worldbible", default="worldbible/worldbible_v1.json")
    a = ap.parse_args()
    batch = Path(a.batch) if Path(a.batch).is_absolute() else ROOT / a.batch
    ix = Index(json.loads((ROOT / a.worldbible).read_text()))
    lines = {l["id"]: l for l in load_lines(ROOT / a.lines)}
    for name in ("cells", "scores"):
        keep = batch / f"{name}.before_rejudge.jsonl"
        if not keep.exists():
            shutil.copy(batch / f"{name}.jsonl", keep)
    cells = [json.loads(l) for l in (batch / "cells.before_rejudge.jsonl").read_text().splitlines()]
    changed = 0
    with (batch / "cells.jsonl").open("w") as fc, (batch / "scores.jsonl").open("w") as fs:
        for c in cells:
            line = lines[c["line_id"]]
            for t in c["attempts"]:
                q, v = judge(line, t["text"], ix, t["meta"].get("finish_reason"))
                if (q, v) != (t["quests"], t["violations"]):
                    changed += 1
                    where = f"{c['line_id']} {c['model']} {c['condition']} r{c['rep']} 시도{t['t']}"
                    print(("경고 - C2 경로가 달라질 수 있다: " if c["condition"] == "C2" else "다시 판정: ") + where)
                t["quests"], t["violations"] = q, v
            fc.write(json.dumps(c, ensure_ascii=False) + "\n")
            fs.write(json.dumps(score_cell(line, c, ix), ensure_ascii=False) + "\n")
    print(f"판정이 바뀐 시도 {changed}")


if __name__ == "__main__":
    main()
