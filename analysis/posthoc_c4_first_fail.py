"""사후 확인 (미리 정한 분석 아님, 2026-11-12 논문 수정 과정에서 더함) - C4 의 실행 시점과 첫 출력 차이.

배경: C4 는 본 실험 뒤 다른 시점에 실행되었다. C4 실행 시점의 모델 버전이 본 실험과 같았는지 밝히고,
첫 출력 차이를 통제한 비교(첫 출력이 실패한 셀만 대상으로 한 교정률)를 더한다.

  1. 모델별로 호출 기록의 날짜 판(meta.generation.model_dated, meta.snapshot_frozen)과 응답 모델 이름(meta.model_returned),
     요청 시각의 범위를 본 실험과 C4 에서 견준다
  2. 첫 출력이 진행 불가였던 셀만으로 조건별 교정률(마지막 출력이 진행 가능인 비율)을 낸다. 라인 군집 부트스트랩 95% 구간,
     진행 가능 ~ 조건 + 모델 라인 군집 GEE(고정 분석과 같은 함수), 대비 C2 대 C4, C4 대 C3 (두 비교를 한 묶음으로 BH 보정)

    .venv/bin/python analysis/posthoc_c4_first_fail.py
"""
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from questline.analysis import _design, bh, contrast, fit_logit, ratio_ci  # noqa: E402

MODELS = ["claude", "gemini", "gpt"]
ver, when = defaultdict(set), defaultdict(list)
for batch in ("main", "selfcorrect_c4"):
    for l in (ROOT / "runs/questline" / batch / "cells.jsonl").read_text().splitlines():
        c = json.loads(l)
        for a in c["attempts"]:
            m = a["meta"]
            g = m.get("generation") or {}
            ver[(batch, c["model"])].add((m.get("snapshot_frozen"), g.get("model_dated"), m.get("model_returned")))
            when[batch].append(m["request_utc"])
print("1. 모델 날짜 판 (고정값, 호출 기록의 날짜 판, 응답 모델 이름)")
for m in MODELS:
    a, b = ver[("main", m)], ver[("selfcorrect_c4", m)]
    print(f"  {m}: 본 실험 {sorted(a, key=str)} | C4 {sorted(b, key=str)} | 같음 {a == b}")
for batch in ("main", "selfcorrect_c4"):
    print(f"  {batch} 요청 시각(UTC): {min(when[batch])} ~ {max(when[batch])}")

rows = []
for batch in ("main", "selfcorrect_c4"):
    for l in (ROOT / "runs/questline" / batch / "scores.jsonl").read_text().splitlines():
        r = json.loads(l)
        rows.append({"line": r["line_id"], "model": r["model"], "cond": r["condition"],
                     "first": r["first_completable"], "final": r["final_completable"]})
print("2. 첫 출력이 진행 불가였던 셀의 교정률")
fail = [r for r in rows if not r["first"] and r["cond"] != "C1"]
for cond in ("C2", "C3", "C4"):
    rs = [r for r in fail if r["cond"] == cond]
    ci = ratio_ci([(r["line"], r["final"], 1) for r in rs])
    n_all = sum(r["cond"] == cond for r in rows)
    print(f"  {cond}: 첫 출력 진행 가능 {n_all - len(rs)}/{n_all}, 교정 {int(ci['num'])}/{len(rs)} = {ci['est']:.3f} [{ci['lo']:.3f}, {ci['hi']:.3f}] | "
          + ", ".join(f"{m} {sum(r['final'] for r in rs if r['model'] == m)}/{sum(r['model'] == m for r in rs)}" for m in MODELS))
X, names = _design(fail, [("cond", ["C4", "C2", "C3"], "cond"), ("model", MODELS, "model")])
f = fit_logit([r["final"] for r in fail], X, [r["line"] for r in fail], names, [(r["cond"], r["model"]) for r in fail])
tests = [(label, contrast(f, w)) for label, w in (("C2 대 C4", {"cond[C2]": 1.0}), ("C4 대 C3", {"cond[C3]": -1.0}))]
adj = bh([h["p"] for _, h in tests])  # 본 실험 뒤 탐색 분석(selfcorrect_c4.py)과 같이 두 비교를 한 묶음으로 BH 보정
for (label, h), q in zip(tests, adj):
    print(f"  {label} ({f['method']}): 오즈비 {math.exp(h['est']):.2f} [{math.exp(h['lo']):.2f}, {math.exp(h['hi']):.2f}], "
          f"p {h['p']:.3g}, BH 보정 p {q:.3g}")
