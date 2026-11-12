"""사후 확인 (미리 정한 분석 아님, 2026-11-12 논문 수정 과정에서 더함) - 검사기 판정이 틀렸다고 가정해도 H1, H2 가 유지되는가.

배경: 주요 결과 전체가 검사기 판정에 기대고 있다. 사람이 판정하지 않았으므로 판정이 얼마나 틀리는지는 모른다.
이 스크립트는 판정이 틀린 비율을 가정하고, 그 비율만큼 마지막 출력의 판정을 C2 에 가장 불리한 방향으로 뒤집은 뒤
고정 분석과 같은 모형(_design, fit_logit, contrast)으로 H1(C2 대 C1), H2(C2 대 C3)를 다시 검정한다.

  가장 불리한 방향   C2 에서 진행 가능으로 판정된 셀의 f 를 진행 불가로, C1 과 C3 에서 진행 불가로 판정된 셀의 f 를
                    진행 가능으로 바꾼다 (검사기가 C2 의 오류는 놓치고, C1 과 C3 에서는 없는 오류를 잡았다고 가정)
  뒤집을 셀         조건 안에서 무작위로 고른다. 가정한 비율마다 REPS 번 되풀이한다
  라인에 몰린 경우   같은 수의 셀을 뒤집되, 라인을 무작위 순서로 늘어놓고 앞 라인의 셀부터 모두 뒤집는다
                    (틀린 판정이 일부 라인에 몰려 있다고 가정). CLUSTER_RATE 에서 REPS 번 되풀이한다

판정이 실제로 얼마나 틀리는지를 재는 분석이 아니다. 틀린 비율이 어느 정도일 때까지 결론이 유지되는지만 보인다.

    .venv/bin/python analysis/posthoc_misjudgment.py
"""
import json
import math
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from questline.analysis import _design, contrast, fit_logit  # noqa: E402

MODELS = ["claude", "gemini", "gpt"]
REPS = 200
RATES = [0.0, 0.05, 0.10, 0.15, 0.20, 0.22, 0.24, 0.25, 0.30]
CLUSTER_RATE = 0.22

rows = []
for l in (ROOT / "runs/questline/main/cells.jsonl").read_text().splitlines():
    c = json.loads(l)
    rows.append({"line": c["line_id"], "model": c["model"], "cond": c["condition"], "ok": not c["attempts"][-1]["violations"]})


def test(ok):
    X, names = _design(rows, [("cond", ["C2", "C1", "C3"], "cond"), ("model", MODELS, "model")])
    f = fit_logit(ok, X, [r["line"] for r in rows], names, [(r["cond"], r["model"]) for r in rows])
    return {o: contrast(f, {f"cond[{o}]": -1.0}) for o in ("C1", "C3")}


idx = {c: {v: [i for i, r in enumerate(rows) if r["cond"] == c and r["ok"] == v] for v in (True, False)} for c in ("C1", "C2", "C3")}
print("가정한 오판 비율 | 뒤집은 셀 수(C2 통과→불가, C1 불가→통과, C3 불가→통과) | 진행 가능 비율 C1, C2, C3 | "
      "H1 오즈비 중앙값 [최소, 최대], p < .05 인 반복 | H2 오즈비 중앙값 [최소, 최대], p < .05 인 반복")
for f in RATES:
    k = {"C2": round(f * len(idx["C2"][True])), "C1": round(f * len(idx["C1"][False])), "C3": round(f * len(idx["C3"][False]))}
    res = {"C1": [], "C3": []}
    rnd = random.Random(20261112)
    for _ in range(1 if f == 0 else REPS):
        ok = [r["ok"] for r in rows]
        for i in rnd.sample(idx["C2"][True], k["C2"]):
            ok[i] = False
        for c in ("C1", "C3"):
            for i in rnd.sample(idx[c][False], k[c]):
                ok[i] = True
        t = test(ok)
        for o in res:
            res[o].append((math.exp(t[o]["est"]), t[o]["p"]))
    rate = {c: (len(idx[c][True]) + (-k[c] if c == "C2" else k[c])) / 360 for c in ("C1", "C2", "C3")}
    out = []
    for o in ("C1", "C3"):
        ors = sorted(x[0] for x in res[o])
        sig = sum(x[1] < 0.05 for x in res[o])
        out.append(f"{ors[len(ors) // 2]:.2f} [{ors[0]:.2f}, {ors[-1]:.2f}], {sig}/{len(ors)}")
    print(f"  {f:.0%} | {k['C2']}, {k['C1']}, {k['C3']} | {rate['C1']:.1%}, {rate['C2']:.1%}, {rate['C3']:.1%} | {out[0]} | {out[1]}")


print(f"틀린 판정이 일부 라인에 몰린 경우 (비율 {CLUSTER_RATE:.0%}, 라인 순서를 무작위로 {REPS} 번)")
k = {"C2": round(CLUSTER_RATE * len(idx["C2"][True])), "C1": round(CLUSTER_RATE * len(idx["C1"][False])), "C3": round(CLUSTER_RATE * len(idx["C3"][False]))}
line_ids = sorted({r["line"] for r in rows})
res = {"C1": [], "C3": []}
rnd = random.Random(20261112)
for _ in range(REPS):
    order = {l: n for n, l in enumerate(rnd.sample(line_ids, len(line_ids)))}
    ok = [r["ok"] for r in rows]
    for c, v in (("C2", True), ("C1", False), ("C3", False)):
        for i in sorted(idx[c][v], key=lambda i: (order[rows[i]["line"]], i))[:k[c]]:
            ok[i] = not v
    t = test(ok)
    for o in res:
        res[o].append((math.exp(t[o]["est"]), t[o]["p"]))
for o, name in (("C1", "H1"), ("C3", "H2")):
    ors = sorted(x[0] for x in res[o])
    ps = sorted(x[1] for x in res[o])
    print(f"  {name}: 오즈비 중앙값 {ors[len(ors) // 2]:.2f} [{ors[0]:.2f}, {ors[-1]:.2f}], p 중앙값 {ps[len(ps) // 2]:.3f}, "
          f"p < .05 인 반복 {sum(x < 0.05 for x in ps)}/{len(ps)}")
