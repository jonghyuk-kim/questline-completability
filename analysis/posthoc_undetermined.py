"""사후 확인 (미리 정한 분석 아님, 2026-11-12 논문 수정 과정에서 더함) - 판정 불가 함정 지점의 분포와 H4 의 민감도.

배경: 조건별, 모델별 판정 불가 지점 수를 제시하고, 판정 불가가 고르게 분포하는지 확인할 수 있게 한다.
고정 분석(analysis-v4)은 판정 불가를 뺀 함정 지점만으로 H4 를 검정한다. 여기서는
  1. 마지막 출력 기준 판정 불가 지점 수를 조건 × 모델 × 함정 종류로 센다
  2. C1 의 판정 불가 지점을 (가) 모두 오류로, (나) 모두 통과로, (다) H4 에 가장 불리하게(소유 변화는 통과, 죽음은 오류)
     처리한 뒤, 고정 분석과 같은 함수(probe_units, _design, fit_logit, contrast)로 H4 GEE 를 다시 맞춘다

    .venv/bin/python analysis/posthoc_undetermined.py
"""
import json
import math
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from questline.analysis import _design, contrast, fit_logit, probe_units  # noqa: E402

rows = [json.loads(x) for x in (ROOT / "runs/questline/main/scores.jsonl").read_text().splitlines()]
MODELS = ["claude", "gemini", "gpt"]

und, tot = Counter(), Counter()
for r in rows:
    for pr in r["final_probes"].values():
        tot[(r["condition"], r["model"], pr["type"])] += 1
        und[(r["condition"], r["model"], pr["type"])] += pr["status"] == "undetermined"
print("판정 불가 지점 수 (마지막 출력, 판정 불가 / 전체)")
for cond in ("C1", "C2", "C3"):
    for typ in ("custody", "death"):
        cells = " ".join(f"{m} {und[(cond, m, typ)]}/{tot[(cond, m, typ)]}" for m in MODELS)
        print(f"  {cond} {typ:8s} {cells} | 합 {sum(und[(cond, m, typ)] for m in MODELS)}/{sum(tot[(cond, m, typ)] for m in MODELS)}")

pu = probe_units(rows, "C1")


def h4(label: str, units: list[dict], err) -> None:
    X, names = _design(units, [("type", ["death", "custody"], "type"), ("model", MODELS, "model")])
    f = fit_logit([err(u) for u in units], X, [u["line"] for u in units], names, [(u["type"], u["model"]) for u in units])
    h = contrast(f, {"type[custody]": 1.0})
    rate = {t: sum(err(u) for u in units if u["type"] == t) / sum(u["type"] == t for u in units) for t in ("custody", "death")}
    print(f"  {label}: 소유 변화 {rate['custody']:.3f} 죽음 {rate['death']:.3f} | {f['method']} 오즈비 "
          f"{math.exp(h['est']):.2f} [{math.exp(h['lo']):.2f}, {math.exp(h['hi']):.2f}], p {h['p']:.3f}")


print("H4 (C1 함정 오류 ~ 함정 종류 + 모델, 라인 군집 GEE)")
h4("판정 불가 제외(고정 분석)", [u for u in pu if u["status"] != "undetermined"], lambda u: u["status"] == "error")
h4("판정 불가를 모두 오류로", pu, lambda u: u["status"] != "kept")
h4("판정 불가를 모두 통과로", pu, lambda u: u["status"] == "error")
h4("가장 불리하게(소유 변화는 통과, 죽음은 오류)", pu,
   lambda u: u["status"] == "error" or (u["status"] == "undetermined" and u["type"] == "death"))
