"""사후 확인 (미리 정한 분석 아님, 2026-11-12 논문 수정 과정에서 더함) - 정적 오류를 뺀 진행 가능 비율.

배경: 주지표인 진행 가능 비율에는 정적 오류(이름 오류, 거처 밖 만남 등)가 함께 들어간다. 상태 의존 오류와
미리 정한 결과(R7)만으로 계산한 비율도 제시하고, C2 의 개선에서 정적 오류 교정이 차지하는 몫을 나눈다.

정의 (마지막 출력 기준)
  고정 분석의 진행 가능      오류가 하나도 없다
  규칙 기준 진행 가능        규칙 R2, R4, R6, R7 의 오류가 없고, 출력을 읽을 수 있다(R0 없음).
                            R1(이름), R3(거처 밖 만남), R5(출입 제한) 오류는 있어도 된다. 논문에 싣는 기준이다
  상태 기준 진행 가능        더 좁힌 기준 - 상태 의존 오류(kind state - 라인 안에서 상태가 바뀐 인물이나 물건의 R2, R4, R6)와
                            미리 정한 결과 미달성(R7)이 없고, 출력을 읽을 수 있다. 상태가 바뀌지 않은 인물이나 물건의
                            R2, R4, R6 은 있어도 된다
읽을 수 없는 출력(R0)은 다른 오류가 있는지 알 수 없으므로 세 기준 모두에서 진행 불가로 둔다.

고정 분석과 같은 함수(ratio_ci, _design, fit_logit, contrast)로 조건별 비율과 구간, C2 대 C1, C2 대 C3 오즈비를 낸다.

    .venv/bin/python analysis/posthoc_state_only.py
"""
import json
import math
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from questline.analysis import _design, contrast, fit_logit, ratio_ci  # noqa: E402

MODELS = ["claude", "gemini", "gpt"]


def load(batch: str) -> list[dict]:
    out = []
    for l in (ROOT / "runs/questline" / batch / "cells.jsonl").read_text().splitlines():
        c = json.loads(l)
        v = c["attempts"][-1]["violations"]
        kinds = Counter(x["kind"] for x in v)
        r0 = any(x["rule"] == "R0" for x in v)
        out.append({"line": c["line_id"], "model": c["model"], "cond": c["condition"],
                    "strict": not v,
                    "rule_ok": not any(x["rule"] in ("R0", "R2", "R4", "R6", "R7") for x in v),
                    "state_ok": not kinds["state"] and not kinds["goal"] and not r0,
                    "has_state": bool(kinds["state"]), "has_goal": bool(kinds["goal"]), "r0": r0,
                    "static_only": bool(v) and not kinds["state"] and not kinds["goal"] and not r0})
    return out


rows = load("main") + load("selfcorrect_c4")
print("조건별 비율 (마지막 출력, 라인 군집 부트스트랩 95% 구간)")
for cond in ("C1", "C2", "C3", "C4"):
    rs = [r for r in rows if r["cond"] == cond]
    a = ratio_ci([(r["line"], r["strict"], 1) for r in rs])
    b = ratio_ci([(r["line"], r["state_ok"], 1) for r in rs])
    g = ratio_ci([(r["line"], r["rule_ok"], 1) for r in rs])
    so = sum(r["static_only"] for r in rs)
    print(f"  {cond}: 고정 분석 {a['est']:.3f} [{a['lo']:.3f}, {a['hi']:.3f}] ({int(a['num'])}/{len(rs)}) | "
          f"규칙 기준 {g['est']:.3f} [{g['lo']:.3f}, {g['hi']:.3f}] ({int(g['num'])}/{len(rs)}) | "
          f"상태 기준 {b['est']:.3f} [{b['lo']:.3f}, {b['hi']:.3f}] ({int(b['num'])}/{len(rs)}) | "
          f"정적 오류만 있는 셀 {so} | 읽을 수 없는 셀 {sum(r['r0'] for r in rs)}")
    print("     모델별 상태 기준:", ", ".join(f"{m} {sum(r['state_ok'] for r in rs if r['model'] == m)}/{sum(r['model'] == m for r in rs)}" for m in MODELS))

main = [r for r in rows if r["cond"] in ("C1", "C2", "C3")]
for key, label in (("strict", "고정 분석 기준"), ("rule_ok", "규칙 기준"), ("state_ok", "상태 기준")):
    X, names = _design(main, [("cond", ["C2", "C1", "C3"], "cond"), ("model", MODELS, "model")])
    f = fit_logit([r[key] for r in main], X, [r["line"] for r in main], names, [(r["cond"], r["model"]) for r in main])
    for other in ("C1", "C3"):
        h = contrast(f, {f"cond[{other}]": -1.0})
        print(f"  {label} C2 대 {other} ({f['method']}): 오즈비 {math.exp(h['est']):.2f} "
              f"[{math.exp(h['lo']):.2f}, {math.exp(h['hi']):.2f}], p {h['p']:.2g}")
