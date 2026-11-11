"""본실험 분석 실행 (연구계획서 4.5, 실험 상세 설계 단계 5). 분석 내용과 규칙은 questline/analysis.py 머리말에 있다.

    .venv/bin/python scripts/analyze_questline.py runs/questline/<배치> --lines scenarios/questlines_v1.yaml --json out.json

배치 폴더의 scores.jsonl 로 모든 분석을 하고, cells.jsonl 은 C1 죽음 함정의 물은 인물 분류와 정가 비용(시도마다 토큰 수 ×
configs 의 price_usd_per_mtok)에만 쓴다. 표를 찍고 --json 이
있으면 결과 전체(적합한 모형의 계수와 공분산 포함)를 남긴다. 단계 3 에서 고정한 뒤에는 고치지 않는다.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import yaml  # noqa: E402

from questline.analysis import CONDS, analyze, cell_tokens, death_class, list_cost  # noqa: E402
from questline.checker import Index  # noqa: E402
from questline.lines import load_lines, probe_distances  # noqa: E402


def ci(d: dict, pct: bool = True, nd: int = 1) -> str:
    if d["est"] is None:
        return f"{d['num']:g}/0"
    f = (lambda x: f"{x * 100:.{nd}f}%") if pct else (lambda x: f"{x:.{nd + 3}f}")
    rng = f" [{f(d['lo'])}, {f(d['hi'])}]" if d["lo"] is not None else ""
    head = f"{d['num']:g}/{d['den']:g} = " if pct else ""
    return f"{head}{f(d['est'])}{rng}"


def test(name: str, t: dict) -> str:
    if t["est"] is None:
        return f"- {name}: 적합 실패 ({t.get('method')})"
    return (f"- {name}: 로그 오즈비 {t['est']:.3f} [{t['lo']:.3f}, {t['hi']:.3f}], 오즈비 {pow(2.718281828, t['est']):.2f}, "
            f"p {t['p']:.4f}, BH 보정 p {t['p_adj']:.4f} → {'지지' if t['supported'] else '지지 안 함'} ({t['method']})")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("batch")
    ap.add_argument("--lines", default="scenarios/questlines_v1.yaml")
    ap.add_argument("--worldbible", default="worldbible/worldbible_v1.json")
    ap.add_argument("--config", default="configs/models.yaml")
    ap.add_argument("--json")
    a = ap.parse_args()
    batch = Path(a.batch) if Path(a.batch).is_absolute() else ROOT / a.batch
    ix = Index(json.loads((ROOT / a.worldbible).read_text()))
    lines = {l["id"]: l for l in load_lines(ROOT / a.lines)}
    rows = [json.loads(x) for x in (batch / "scores.jsonl").read_text().splitlines()]
    cells = {(c["line_id"], c["model"], c["condition"], c["rep"]): c
             for c in map(json.loads, (batch / "cells.jsonl").read_text().splitlines())}
    prices = {m: v["price_usd_per_mtok"] for m, v in yaml.safe_load((ROOT / a.config).read_text())["models"].items()}
    for r in rows:
        att = cells[(r["line_id"], r["model"], r["condition"], r["rep"])]["attempts"]
        r["cost_list_usd"], r["calls"], r["tokens"] = list_cost(att, prices[r["model"]]), len(att), cell_tokens(att)
    dcls = []
    for r in rows:
        if r["condition"] != "C1":
            continue
        quests = cells[(r["line_id"], r["model"], r["condition"], r["rep"])]["attempts"][-1]["quests"]
        for qn, pr in r["final_probes"].items():
            if pr["type"] == "death":
                dcls.append({"line": r["line_id"], "class": death_class(lines[r["line_id"]], quests, pr["status"], int(qn), ix)})
    pdist = {(lid, q): d for lid, ln in lines.items() for q, d in probe_distances(ln, ix).items()}
    res = analyze(rows, dcls, pdist)
    res["batch"] = str(batch.relative_to(ROOT)) if batch.is_relative_to(ROOT) else str(batch)

    print(f"# 분석 - {res['batch']} (셀 {res['cells']}, 라인 {res['lines']}, 모델 {', '.join(res['models'])})")
    print("\n## 기초 통계 (마지막 출력, 라인 군집 부트스트랩 95% 구간)")
    for c in CONDS:
        d = res["descriptive"][c]
        print(f"- {c}: 진행 가능 {ci(d['completable'])}, 정적 오류 라인 {ci(d['static_error'])}, "
              f"함정 오류 소유 {ci(d['probe_error']['custody'])}, 죽음 {ci(d['probe_error']['death'])}")
        print("  - 모델별 진행 가능: " + ", ".join(f"{m} {ci(v)}" for m, v in d["by_model"].items()))
    q = res["rq1"]
    print("\n## RQ1 - C1 함정 지점 오류율 (판정 불가 제외)")
    print(f"- 소유 {ci(q['by_type']['custody'])}, 죽음 {ci(q['by_type']['death'])}")
    print("- 모델별: " + ", ".join(f"{k} {ci(v)}" for k, v in q["by_model_type"].items()))
    print("- 오류 유형별: " + ", ".join(f"{k} {ci(v)}" for k, v in q["by_error_type"].items()))
    print("- 판정 불가 비율: " + ", ".join(f"{m} {ci(v)}" for m, v in q["undetermined_by_model"].items()))
    ds = res.get("death_sensitivity")
    if ds:
        n = ds["counts"]
        print(f"- 죽음 함정 물은 인물: ① {n.get('1', 0)}, ② {n.get('2', 0)}, ③ {n.get('3', 0)}, ④ {n.get('4', 0)}, "
              f"판정 불가 {n.get('-', 0)}. 오류율 {ds['error_rate']:.3f}, ③을 판정 불가로 돌린 오류율 "
              f"{ds['error_rate_q3_undetermined']:.3f}, 지킴 가운데 ③ {ds['q3_of_kept']:.3f}")
    dd = res.get("distance")
    if dd:
        print("- 상태 변화와 함정 사이 거리별 오류율 (탐색): " + ", ".join(f"{k} {ci(v)}" for k, v in dd["by_type_distance"].items()))
        t = dd["trend"]
        print(f"  - 거리 추세 ({dd['method']}, BH 묶음 밖): 퀘스트 하나 멀어질 때 로그 오즈비 " +
              (f"{t['est']:.3f} [{t['lo']:.3f}, {t['hi']:.3f}], p {t['p']:.4f}" if t["est"] is not None else "적합 실패"))
    print("\n## 가설 (H1, H2, H4 는 BH 보정 한 묶음)")
    print(test("H1 C2 대 C1 진행 가능", res["h1"]))
    print(test("H2 C2 대 C3 진행 가능", res["h2"]))
    print(test("H4 소유 대 죽음 함정 오류", res["h4"]))
    hx = res["h4_by_model"]
    w = hx["interaction"]
    print(f"- H4 탐색 - 모델별 소유 대 죽음 ({hx['method']}, BH 묶음 밖): " + ", ".join(
        f"{m} {v['est']:.3f} [{v['lo']:.3f}, {v['hi']:.3f}]" if v["est"] is not None else f"{m} 실패"
        for m, v in hx["by_model"].items()) +
        (f"; 상호작용 결합 Wald χ²({w['df']}) {w['chi2']:.2f}, p {w['p']:.4f}" if w["p"] is not None
         else "; 모델이 하나라 상호작용 없음" if w["df"] == 0 else "; 상호작용 검정 실패"))
    h3 = res["h3"]
    print(f"- H3 모델별 C2 대 C1 ({h3['method']}): " + ", ".join(
        f"{m} {v['est']:.3f} [{v['lo']:.3f}, {v['hi']:.3f}]" if v["est"] is not None else f"{m} 실패"
        for m, v in h3["by_model"].items()) + f" → {'지지' if h3['supported'] else '지지 안 함'}")
    for k in ("h4", "h4_by_model", "distance", "h3"):
        if k in res and res[k]["fit"].get("gee_failure"):
            print(f"  - {k.upper()} GEE 실패로 대체 규칙 적용: {res[k]['fit']['gee_failure']}")
    if res["fit_h12"].get("gee_failure"):
        print(f"  - H1, H2 GEE 실패로 대체 규칙 적용: {res['fit_h12']['gee_failure']}")
    print("\n## RQ3 비용 (셀 평균 - 주 지표는 정가 비용, 청구액은 캐시 할인이 섞인 보조)과 조작 점검")
    for c in CONDS:
        r3, mp = res["rq3"][c], res["manipulation"][c]
        print(f"- {c}: 정가 비용 ${ci(r3['cost_list_usd'], False)} (청구액 ${ci(r3['cost_billed_usd'], False)}), "
              f"지연 {ci(r3['latency_s'], False, 0)}초, 재생성 {ci(r3['regenerations'], False, 0)}, "
              f"진행 가능 출력당 정가 ${ci(r3['cost_per_completable_list'], False)} "
              f"(청구액 ${ci(r3['cost_per_completable_billed'], False)}), "
              f"진행 가능 출력당 호출 {ci(r3['calls_per_completable'], False, 0)}회, 토큰 {ci(r3['tokens_per_completable'], False, -3)}, "
              f"퀘스트당 단계 {ci(mp['steps_per_quest'], False, 0)}, 개요 결과 {ci(mp['goals_met'])}")
    print("- 진행 가능 출력당 값의 조건 사이 비율 (가격이 바뀌어도 쓰는 지표): " + "; ".join(
        f"{k} " + ", ".join(f"{m} {v['est']:.2f} [{v['lo']:.2f}, {v['hi']:.2f}]" if v["lo"] is not None
                           else f"{m} {v['est']}" for m, v in d.items())
        for k, d in res["rq3_ratio"].items()))
    if a.json:
        Path(a.json).write_text(json.dumps(res, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
