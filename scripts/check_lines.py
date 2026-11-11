"""라인 풀 점검 - 실험 상세 설계 1-2 의 완료조건.

    .venv/bin/python scripts/check_lines.py scenarios/questlines_v1.yaml scenarios/questlines_pre.yaml

형식 검사(함정 배분 포함), 모범 풀이 위반 0, 함정 지점이 실제로 함정인지, 함정 개요의 금지어, 같은 사물 이동 횟수를 보고
라인 풀 전체의 구성(함정 순서, 죽는 인물, 옮기는 사물)을 찍는다. 문제가 하나라도 있으면 종료 코드 1.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from questline.checker import Index  # noqa: E402
from questline.lines import PROBE_MIX, audit_line, load_lines, parse_probe_mix, validate_lines  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("lines", nargs="+")
    ap.add_argument("--worldbible", default="worldbible/worldbible_v1.json")
    ap.add_argument("--probe-mix", default=",".join(f"{k}={v}" for k, v in PROBE_MIX.items()))
    a = ap.parse_args()

    ix = Index(json.loads((ROOT / a.worldbible).read_text()))
    mix = parse_probe_mix(a.probe_mix)
    all_lines, problems = [], []
    for path in a.lines:
        lines = load_lines(ROOT / path)
        problems += validate_lines(lines, ix, probes_per_line=mix)
        for line in lines:
            problems += audit_line(line, ix)
        all_lines += lines
    ids = [l["id"] for l in all_lines]
    problems += [f"{i}: 파일 사이에서 id 가 겹친다" for i, c in Counter(ids).items() if c > 1]

    orders = Counter("".join(t[0] for _, t in sorted(l["probes"].items())) for l in all_lines)
    deaths = Counter(ev["dead"] for l in all_lines for ev in l.get("events") or [] if "dead" in ev)
    deaths += Counter(g["dead"] for l in all_lines for q in l["quests"] for g in q.get("goals") or [] if "dead" in g)
    items = Counter(g["hold"][0] for l in all_lines for q in l["quests"] for g in q.get("goals") or [] if "hold" in g)
    n_q = Counter(len(l["quests"]) for l in all_lines)
    print(f"라인 {len(all_lines)}개 (퀘스트 수 {dict(n_q)}), 함정 순서(c=소유, d=죽음) {dict(orders)}")
    print("죽는 인물: " + ", ".join(f"{ix.name(k)} {v}" for k, v in deaths.most_common()))
    print("옮기는 사물(목표 횟수): " + ", ".join(f"{ix.name(k)} {v}" for k, v in items.most_common()))
    if problems:
        print(f"\n문제 {len(problems)}건:")
        for p in problems:
            print("  " + p)
        sys.exit(1)
    print("\n문제 없음 - 모범 풀이 위반 0, 함정 지점 확인, 형식 통과")


if __name__ == "__main__":
    main()
