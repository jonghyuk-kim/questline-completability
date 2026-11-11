"""추가 탐색 실험 - 자기 수정 조건(C4)과 검사기 피드백(C2), 다시 뽑기(C3)의 비교 (본실험 뒤 더함, 2026-10-13).

연구계획서의 가설(H1~H4)과 고정 분석(analysis-v4)에는 들지 않는 탐색 실험이다. 기존 방법과 비교하려고, 외부 피드백 없이
모델이 스스로 고치는 방식(선행연구의 자기 수정)을 조건으로 더해 비교한다.
이 스크립트는 C4 배치를 돌리기 전에 짜서 커밋했다 - 결과를 본 뒤 분석을 고르지 않는다.

조건 (questline/run.py)
  C4  위반이 있으면 앞 출력과 "진행할 수 없는 곳이 있다. 어디가 문제인지 스스로 찾는다"(questline.prompting.selfcheck_message)를
      대화에 붙여 다시 생성. 검사기는 멈출지만 정한다(통과 여부). C2 와 대화 구조, seed, 최대 재생성 횟수가 같고 위반 목록만 없다.
      그래서 C2 대 C4 의 차이는 위반 목록의 내용 하나다. C4 대 C3 은 앞 출력과 통과 여부를 보는지의 차이다.

자료
  C1~C3  runs/questline/main (본실험, 고친 것 없음)
  C4     runs/questline/selfcorrect_c4 (같은 라인 40 × 모델 3 × 반복 3 = 360셀, 같은 configs, 같은 seed 규칙,
         실행 전 날짜 판 대조). 실행 시점이 본실험보다 늦다는 점은 결과와 함께 보고한다.

분석 (고정 분석과 같은 함수 - questline.analysis)
  1. 조건별 진행 가능률(마지막 출력), 모델별 진행 가능률 - 라인 군집 부트스트랩 95% 구간
  2. 진행 가능 여부 ~ 조건(C4 기준) + 모델, 라인 군집 GEE (C2, C3, C4 셀). 대비 C2 대 C4, C4 대 C3 의 로그 오즈비.
     두 p 를 한 묶음으로 BH 보정한다. 예상 방향은 C2 > C4(선행연구 Huang 외, ICLR 2024 - 외부 피드백 없는 자기 수정은 효과가 작다).
     C4 대 C3 은 방향을 정하지 않는다(양측)
  3. 조건 × 모델 상호작용 모형에서 모델별 C2 대 C4 효과(방향 확인)
  4. 진행 가능 출력당 호출 수, 토큰 수, 정가 비용의 비율 C2/C4, C4/C3 (라인 군집 부트스트랩)
  5. 평균 재생성 횟수, 마지막 출력의 함정 오류율(소유, 죽음), 조작 점검(퀘스트당 단계 수, 개요 결과 달성률)
  6. 점검: C4 첫 출력의 진행 가능률(같은 요청과 seed 라 C1 과 가까워야 한다 - 실행 시점 차이의 확인)

    .venv/bin/python analysis/selfcorrect_c4.py --json analysis/selfcorrect_c4.json
"""
import argparse
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import yaml  # noqa: E402

from questline.analysis import (_design, bh, cell_tokens, contrast, fit_logit, list_cost, per_success_ratio,  # noqa: E402
                                probe_units, ratio_ci)

MAIN, C4 = ROOT / "runs/questline/main", ROOT / "runs/questline/selfcorrect_c4"


def load(batch: Path, prices: dict) -> list[dict]:
    rows = [json.loads(x) for x in (batch / "scores.jsonl").read_text().splitlines()]
    cells = {(c["line_id"], c["model"], c["condition"], c["rep"]): c
             for c in map(json.loads, (batch / "cells.jsonl").read_text().splitlines())}
    for r in rows:
        att = cells[(r["line_id"], r["model"], r["condition"], r["rep"])]["attempts"]
        r["cost_list_usd"], r["calls"], r["tokens"] = list_cost(att, prices[r["model"]]), len(att), cell_tokens(att)
    return rows


def pct(d: dict) -> str:
    return f"{d['num']:g}/{d['den']:g} = {d['est'] * 100:.1f}% [{d['lo'] * 100:.1f}, {d['hi'] * 100:.1f}]"


def odds(t: dict) -> str:
    return (f"로그 오즈비 {t['est']:.3f} [{t['lo']:.3f}, {t['hi']:.3f}], 오즈비 {math.exp(t['est']):.2f} "
            f"[{math.exp(t['lo']):.2f}, {math.exp(t['hi']):.2f}], p {t['p']:.4f}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json")
    a = ap.parse_args()
    prices = {m: v["price_usd_per_mtok"] for m, v in yaml.safe_load((ROOT / "configs/models.yaml").read_text())["models"].items()}
    rows = [r for r in load(MAIN, prices)] + load(C4, prices)
    c4 = [r for r in rows if r["condition"] == "C4"]
    if len(c4) != 360 or len({(r["line_id"], r["model"], r["rep"]) for r in c4}) != 360:
        sys.exit(f"C4 셀이 360개가 아니거나 중복이 있다: {len(c4)}")
    models = sorted({r["model"] for r in rows})
    conds = ("C1", "C2", "C3", "C4")
    res: dict = {"models": models, "cells_c4": len(c4)}

    # 1, 5
    desc = {}
    for c in conds:
        rs = [r for r in rows if r["condition"] == c]
        pu = [u for u in probe_units(rows, c) if u["status"] != "undetermined"]
        desc[c] = {"completable": ratio_ci([(r["line_id"], r["final_completable"], 1) for r in rs]),
                   "by_model": {m: ratio_ci([(r["line_id"], r["final_completable"], 1) for r in rs if r["model"] == m])
                                for m in models},
                   "first_completable": ratio_ci([(r["line_id"], r["first_completable"], 1) for r in rs]),
                   "regenerations": ratio_ci([(r["line_id"], r["regenerations"], 1) for r in rs]),
                   "probe_error": {t: ratio_ci([(u["line"], u["status"] == "error", 1) for u in pu if u["type"] == t])
                                   for t in ("custody", "death")},
                   "steps_per_quest": ratio_ci([(r["line_id"], r["final_steps_per_quest"], 1) for r in rs
                                                if r["final_steps_per_quest"] is not None]),
                   "goals_met": ratio_ci([(r["line_id"], r["final_goals_met"], r["final_goals_total"]) for r in rs]),
                   "calls_per_completable": ratio_ci([(r["line_id"], r["calls"], r["final_completable"]) for r in rs]),
                   "tokens_per_completable": ratio_ci([(r["line_id"], r["tokens"], r["final_completable"]) for r in rs]),
                   "cost_list_per_completable": ratio_ci([(r["line_id"], r["cost_list_usd"], r["final_completable"]) for r in rs])}
    res["descriptive"] = desc

    # 2
    rr = [r for r in rows if r["condition"] in ("C2", "C3", "C4")]
    y, g, cells = [r["final_completable"] for r in rr], [r["line_id"] for r in rr], [(r["condition"], r["model"]) for r in rr]
    X, names = _design(rr, [("cond", ["C4", "C2", "C3"], "condition"), ("model", models, "model")])
    f = fit_logit(y, X, g, names, cells)
    if f["method"] == "failed":
        sys.exit(f"GEE 실패, 칸이 비지 않아 대체하지 않는다(고정 분석과 같은 규칙): {f['reason']}")
    tests = {"C2_vs_C4": contrast(f, {"cond[C2]": 1.0}), "C4_vs_C3": contrast(f, {"cond[C3]": -1.0})}
    for k, p in zip(tests, bh([t["p"] for t in tests.values()])):
        tests[k]["p_adj"] = p
    res["tests"], res["method"], res["fit"] = tests, f["method"], f

    # 3
    X, names = _design(rr, [("cond", ["C4", "C2", "C3"], "condition"), ("model", models, "model")])
    for cl in ("C2", "C3"):
        for m in models[1:]:
            names.append(f"cond[{cl}]:model[{m}]")
            for row, r in zip(X, rr):
                row.append(float(r["condition"] == cl and r["model"] == m))
    f3 = fit_logit(y, X, g, names, cells)
    res["c2_vs_c4_by_model"] = {m: contrast(f3, {"cond[C2]": 1.0} | ({f"cond[C2]:model[{m}]": 1.0} if m != models[0] else {}))
                                for m in models}
    res["method_by_model"] = f3["method"]

    # 4
    res["ratios"] = {f"{x}/{z}": {k: per_success_ratio(rows, fld, x, z)
                                  for k, fld in (("calls", "calls"), ("tokens", "tokens"), ("cost_list", "cost_list_usd"))}
                     for x, z in (("C2", "C4"), ("C4", "C3"))}

    print(f"# 추가 탐색 - 자기 수정 C4 (C4 {len(c4)}셀 + 본실험 C1~C3)")
    for c in conds:
        d = desc[c]
        print(f"- {c}: 진행 가능 {pct(d['completable'])}, 첫 출력 진행 가능 {pct(d['first_completable'])}, "
              f"평균 재생성 {d['regenerations']['est']:.2f}, 함정 오류 소유 {pct(d['probe_error']['custody'])}, "
              f"죽음 {pct(d['probe_error']['death'])}")
        print("  - 모델별 진행 가능: " + ", ".join(f"{m} {v['est'] * 100:.1f}%" for m, v in d["by_model"].items()))
        print(f"  - 진행 가능 출력당 호출 {d['calls_per_completable']['est']:.2f}, 토큰 {d['tokens_per_completable']['est']:,.0f}, "
              f"정가 ${d['cost_list_per_completable']['est']:.4f}; 단계/퀘스트 {d['steps_per_quest']['est']:.2f}, "
              f"개요 결과 달성 {d['goals_met']['est'] * 100:.1f}%")
    print(f"\n## 진행 가능 GEE ({f['method']}, BH 는 두 비교 한 묶음)")
    for k, t in tests.items():
        print(f"- {k}: {odds(t)}, BH 보정 p {t['p_adj']:.4f}")
    print(f"- 모델별 C2 대 C4 ({f3['method']}): " + ", ".join(f"{m} {t['est']:.3f} [{t['lo']:.3f}, {t['hi']:.3f}]"
                                                         for m, t in res["c2_vs_c4_by_model"].items()))
    print("\n## 진행 가능 출력당 비율")
    for k, v in res["ratios"].items():
        print(f"- {k}: " + ", ".join(f"{n} {t['est']:.2f} [{t['lo']:.2f}, {t['hi']:.2f}]" for n, t in v.items()))
    if a.json:
        Path(a.json).write_text(json.dumps(res, ensure_ascii=False, indent=1, default=float))


if __name__ == "__main__":
    main()
