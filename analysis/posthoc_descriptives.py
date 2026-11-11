"""사후 기술 (미리 정하지 않음, 2026-10-13 논문 원고 최종 검토에서 더함) - 원고에 싣는 기술 수치 세 가지의 출처.

1. C1 진행 불가 라인의 위반 구성 - 상태 의존 위반(kind state)을 하나라도 포함한 라인 비율, 정적 위반만 있는 라인 비율
2. 조건별 시도 회차 누적 진행 가능률 - 시도 1, 2, 3 회차까지 위반 없는 출력이 한 번이라도 나온 셀의 비율 (C2, C3, C4)
3. 재생성을 하고도 실패한 셀 가운데 첫 출력과 같은 (퀘스트, 규칙) 위반이 마지막 출력에 남은 비율 (C2, C3, C4)
4. 첫 출력에서 오류였던 죽음 함정이 마지막 출력에서 어떻게 판정되었는지 (C2, C3) - 2026-10-14 원고 재검토에서 더함
5. 진행 가능으로 센 셀 가운데 마지막 출력에 판정 불가 함정이 남은 셀 수 (C1~C4) - 2026-10-14 원고 재검토에서 더함
6. C3, C4 의 첫 출력과 마지막 출력 진행 가능 셀 수, 모델별 첫 출력 - 2026-10-14 원고 재검토에서 더함
7. 공급사 응답이 오류 상태(finish_reason error)로 끝난 호출, C4 재생성에서 앞 출력을 그대로 다시 낸 횟수(모델별) - 2026-10-14 원고 재검토에서 더함

검정이 아니라 기술이다. 자료는 runs/questline/main(C1~C3)과 runs/questline/selfcorrect_c4(C4).

    .venv/bin/python analysis/posthoc_descriptives.py
2026-10-13 결과: 1. C1 진행 불가 285 가운데 상태 의존 위반 포함 231(81.1%), 정적 위반만 40(14.0%),
개요 결과 위반만 11(3.9%), 정적과 개요 결과 위반 3(1.1%)
2. C2 22.8 / 72.2 / 86.1%, C3 23.6 / 35.8 / 43.3%, C4 20.0 / 29.4 / 36.7%
3. C2 34/50(68%), C3 148/204(73%), C4 213/228(93%)
2026-10-14 결과: 4. C2 첫 출력 죽음 함정 오류 70 → 지킴 66, 판정 불가 4 / C3 67 → 지킴 37, 오류 28, 판정 불가 2
5. C1 1, C2 6, C3 3, C4 5
6. 첫 출력 C3 85(claude 15, gemini 33, gpt 37), C4 72(11, 33, 28) / 마지막 C3 156, C4 132
7. 오류 상태 응답 본실험 4, C4 1(모두 GPT) / C4 같은 출력 재제출 claude 85/212, gemini 1/158, gpt 4/172
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
cells = [json.loads(x) for b in ("main", "selfcorrect_c4")
         for x in (ROOT / "runs/questline" / b / "cells.jsonl").read_text().splitlines()]

c1 = [c for c in cells if c["condition"] == "C1" and c["attempts"][-1]["violations"]]
kinds = [{v["kind"] for v in c["attempts"][-1]["violations"]} for c in c1]
n_state, n_static_only = sum("state" in k for k in kinds), sum(k == {"static"} for k in kinds)
print(f"1. C1 진행 불가 {len(c1)}: 상태 의존 위반 포함 {n_state} ({n_state / len(c1):.1%}), "
      f"정적 위반만 {n_static_only} ({n_static_only / len(c1):.1%})")
n_goal_only, n_static_goal = sum(k == {"goal"} for k in kinds), sum(k == {"static", "goal"} for k in kinds)
print(f"   나머지: 개요 결과 위반만 {n_goal_only} ({n_goal_only / len(c1):.1%}), 정적과 개요 결과 위반 {n_static_goal} ({n_static_goal / len(c1):.1%})")

for cond in ("C2", "C3", "C4"):
    cs = [c for c in cells if c["condition"] == cond]
    cum = [sum(any(not a["violations"] for a in c["attempts"][:t + 1]) for c in cs) / len(cs) for t in range(3)]
    print(f"2. {cond} 누적 진행 가능 (시도 1, 2, 3): " + " / ".join(f"{x:.1%}" for x in cum))

for cond in ("C2", "C3", "C4"):
    failed = [c for c in cells if c["condition"] == cond and len(c["attempts"]) > 1 and c["attempts"][-1]["violations"]]
    key = lambda vs: {(v.get("quest"), v["rule"]) for v in vs}  # noqa: E731
    same = sum(bool(key(c["attempts"][0]["violations"]) & key(c["attempts"][-1]["violations"])) for c in failed)
    print(f"3. {cond} 재생성 뒤 실패 {len(failed)} 가운데 첫 출력과 같은 위반이 남은 셀 {same} ({same / len(failed):.0%})")

scores = [json.loads(x) for x in (ROOT / "runs/questline/main/scores.jsonl").read_text().splitlines()]
for cond in ("C2", "C3"):
    trans = [r["final_probes"][q]["status"] for r in scores if r["condition"] == cond
             for q, u in r["first_probes"].items() if u["type"] == "death" and u["status"] == "error"]
    print(f"4. {cond} 첫 출력 죽음 함정 오류 {len(trans)} → 마지막 출력 "
          + ", ".join(f"{k} {trans.count(k)}" for k in ("kept", "error", "undetermined")))

undet = {}
for b in ("main", "selfcorrect_c4"):
    for x in (ROOT / "runs/questline" / b / "scores.jsonl").read_text().splitlines():
        r = json.loads(x)
        if r["final_completable"] and any(u["status"] == "undetermined" for u in r["final_probes"].values()):
            undet[r["condition"]] = undet.get(r["condition"], 0) + 1
print("5. 진행 가능 셀 가운데 판정 불가 함정이 남은 셀: " + ", ".join(f"{c} {undet.get(c, 0)}" for c in ("C1", "C2", "C3", "C4")))

first, final = {}, {}
for b in ("main", "selfcorrect_c4"):
    for x in (ROOT / "runs/questline" / b / "scores.jsonl").read_text().splitlines():
        r = json.loads(x)
        if r["condition"] in ("C3", "C4"):
            for k in ((r["condition"], "all"), (r["condition"], r["model"])):
                first[k] = first.get(k, 0) + r["first_completable"]
            final[r["condition"]] = final.get(r["condition"], 0) + r["final_completable"]
for c in ("C3", "C4"):
    print(f"6. {c} 첫 출력 진행 가능 {first[(c, 'all')]} (" + ", ".join(f"{m} {first[(c, m)]}" for m in ("claude", "gemini", "gpt"))
          + f"), 마지막 {final[c]}")

for b in ("main", "selfcorrect_c4"):
    errs = [(c["line_id"], c["model"], c["condition"], c["rep"], a["t"])
            for c in (json.loads(x) for x in (ROOT / "runs/questline" / b / "cells.jsonl").read_text().splitlines())
            for a in c["attempts"] if a["meta"].get("finish_reason") == "error"]
    print(f"7. {b} 오류 상태 응답 {len(errs)}: {errs}")
same, tot = {}, {}
for c in (json.loads(x) for x in (ROOT / "runs/questline/selfcorrect_c4/cells.jsonl").read_text().splitlines()):
    for p_, q_ in zip(c["attempts"], c["attempts"][1:]):
        tot[c["model"]] = tot.get(c["model"], 0) + 1
        same[c["model"]] = same.get(c["model"], 0) + (p_["text"].strip() == q_["text"].strip())
print("7. C4 재생성에서 앞 출력을 그대로 다시 냄: " + ", ".join(f"{m} {same[m]}/{tot[m]}" for m in sorted(tot)))
