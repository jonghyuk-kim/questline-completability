"""사후 확인 (미리 정한 분석 아님, 2026-11-12 논문 수정 과정에서 더함) - 함정 종류별 교정 비율과 피드백 정보량.

배경: C2 의 피드백은 소유 변화 오류에는 현재 소유자를 함께 주고 죽음 함정에는 사망 사실만 준다. 이 정보량
차이가 함정 종류별 교정률 해석에 미치는 영향을 논의한다.

첫 출력에서 오류로 판정된 함정 지점을 단위로, 마지막 출력에서 통과(kept)로 바뀐 비율을 조건과 함정 종류별로 낸다.
마지막 출력에서 판정 불가가 된 지점은 교정되지 않은 것으로 센다. 라인 군집 부트스트랩 95% 구간.
C2 와 C3 의 지점으로 통과 여부 ~ 조건 × 함정 종류 + 모델 라인 군집 GEE 를 맞춰(고정 분석과 같은 함수),
함정 종류별 C2 대 C3 오즈비와 상호작용 항(소유 변화에서 C2 의 이득이 죽음 함정보다 큰가)을 본다.

    .venv/bin/python analysis/posthoc_trap_correction.py
"""
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

from questline.analysis import contrast, fit_logit, ratio_ci  # noqa: E402

MODELS = ["claude", "gemini", "gpt"]
units = []
for batch in ("main", "selfcorrect_c4"):
    for l in (ROOT / "runs/questline" / batch / "scores.jsonl").read_text().splitlines():
        r = json.loads(l)
        for q, p in r["first_probes"].items():
            if p["status"] == "error":
                units.append({"line": r["line_id"], "model": r["model"], "cond": r["condition"], "type": p["type"],
                              "rules": p["rules"], "kept": r["final_probes"][q]["status"] == "kept"})
print("첫 출력에서 오류였던 함정 지점이 마지막 출력에서 통과한 비율")
for cond in ("C2", "C3", "C4"):
    for typ, label in (("custody", "소유 변화"), ("death", "죽음")):
        us = [u for u in units if u["cond"] == cond and u["type"] == typ]
        ci = ratio_ci([(u["line"], u["kept"], 1) for u in us])
        print(f"  {cond} {label}: {int(ci['num'])}/{len(us)} = {ci['est']:.3f} [{ci['lo']:.3f}, {ci['hi']:.3f}]")
us = [u for u in units if u["cond"] == "C2" and u["type"] == "custody"]
for rule, label in (("R4", "잘못된 출처(R4)"), ("R6", "되찾는 단계 누락(R6)")):
    s = [u for u in us if rule in u["rules"]]
    print(f"  C2 소유 변화 가운데 {label}: {sum(u['kept'] for u in s)}/{len(s)}")

d = [u for u in units if u["cond"] in ("C2", "C3")]
names = ["const", "cond[C2]", "type[custody]", "cond[C2]:type[custody]", "model[gemini]", "model[gpt]"]
X = np.array([[1.0, u["cond"] == "C2", u["type"] == "custody", u["cond"] == "C2" and u["type"] == "custody",
               u["model"] == "gemini", u["model"] == "gpt"] for u in d], dtype=float)
f = fit_logit([u["kept"] for u in d], X, [u["line"] for u in d], names, [(u["cond"], u["type"], u["model"]) for u in d])


def show(label, w):
    h = contrast(f, w)
    print(f"  {label} ({f['method']}): 오즈비 {math.exp(h['est']):.2f} [{math.exp(h['lo']):.2f}, {math.exp(h['hi']):.2f}], p {h['p']:.3g}")


print("C2 대 C3 (통과 여부 ~ 조건 × 함정 종류 + 모델)")
show("죽음 함정에서 C2 대 C3", {"cond[C2]": 1.0})
show("소유 변화 함정에서 C2 대 C3", {"cond[C2]": 1.0, "cond[C2]:type[custody]": 1.0})
show("상호작용(소유 변화의 C2 이득 ÷ 죽음 함정의 C2 이득)", {"cond[C2]:type[custody]": 1.0})
