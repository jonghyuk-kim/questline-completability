"""사후 확인 (미리 정한 분석 아님, 2026-10-13 논문 원고 검토에서 더함) - 죽음 함정 민감도 기준에서 H4 가 유지되는가.

고정 분석(analysis-v4)은 죽음 함정의 물은 인물 분류 ③(그 라인 개요에 이름이 나온 다른 산 인물)을 판정 불가로 돌린 오류율만 낸다.
여기서는 같은 함수(death_class, probe_units, _design, fit_logit, contrast)로 ③ 을 판정 불가로 돌린 뒤 H4 GEE 를 다시 맞춘다.

    .venv/bin/python analysis/sensitivity_h4_death_q3.py
2026-10-15 결과(death_class 이름 대조 정정 뒤, analysis/main_results.md "고정 분석 정정"): H4 로그 오즈비 0.300 [-0.241, 0.841],
오즈비 1.35 [0.79, 2.32], p 0.277 (원래 1.70 [1.06, 2.72], p 0.029. 정정 전 2026-10-13 결과는 1.34 [0.78, 2.31], p 0.294).
모델별 ③: gpt 24/81(지킴), claude 16/91, gemini 11/107. gpt 의 죽음 함정 오류율은 29.6% 에서 37.4%(34/91) 로 오른다.
"""
import json
import math
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from questline.analysis import _design, contrast, death_class, fit_logit, probe_units  # noqa: E402
from questline.checker import Index  # noqa: E402
from questline.lines import load_lines  # noqa: E402

ix = Index(json.loads((ROOT / "worldbible/worldbible_v1.json").read_text()))
lines = {l["id"]: l for l in load_lines(ROOT / "scenarios/questlines_v1.yaml")}
b = ROOT / "runs/questline/main"
rows = [json.loads(x) for x in (b / "scores.jsonl").read_text().splitlines()]
cells = {(c["line_id"], c["model"], c["condition"], c["rep"]): c for c in map(json.loads, (b / "cells.jsonl").read_text().splitlines())}
cls = {}
for r in rows:
    if r["condition"] != "C1":
        continue
    q = cells[(r["line_id"], r["model"], "C1", r["rep"])]["attempts"][-1]["quests"]
    for qn, pr in r["final_probes"].items():
        if pr["type"] == "death":
            cls[(r["line_id"], r["model"], r["rep"], int(qn))] = death_class(lines[r["line_id"]], q, pr["status"], int(qn), ix)
pu = probe_units(rows, "C1")
print("모델별 분류:", dict(sorted(Counter((u["model"], cls[(u["line"], u["model"], u["rep"], u["quest"])]) for u in pu if u["type"] == "death").items())))
det = [u for u in pu if u["status"] != "undetermined"
       and not (u["type"] == "death" and cls[(u["line"], u["model"], u["rep"], u["quest"])] == "3")]
models = sorted({u["model"] for u in det})
X, names = _design(det, [("type", ["death", "custody"], "type"), ("model", models, "model")])
f = fit_logit([u["status"] == "error" for u in det], X, [u["line"] for u in det], names, [(u["type"], u["model"]) for u in det])
h = contrast(f, {"type[custody]": 1.0})
print(f"H4 (③ 판정 불가) {f['method']}: 로그 오즈비 {h['est']:.3f} [{h['lo']:.3f}, {h['hi']:.3f}], "
      f"오즈비 {math.exp(h['est']):.2f} [{math.exp(h['lo']):.2f}, {math.exp(h['hi']):.2f}], p {h['p']:.3f}")
