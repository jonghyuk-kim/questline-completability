"""사후 확인 (미리 정한 분석 아님, 2026-11-12 논문 수정 과정에서 더함) - 논문 고찰 장에 실은 수치.

배경: 고찰을 더해 (1) C4 가 C3 보다 낮은 이유, (2) 모델별 함정 오류의 차이, (4) 설정집과 라인에 기록하는 비용을 논의한다.
전체 값(C3, C4 에서 같은 위반이 남은 셀, C4 가 앞 출력을 그대로 다시 낸 횟수)은 posthoc_descriptives.py 가 낸다. 여기서는
  1. 재생성 뒤에도 실패한 셀 가운데 첫 출력과 같은 위반(같은 퀘스트의 같은 규칙)이 남은 셀을 모델별로 센다 (C3, C4)
  2. C1 마지막 출력의 함정 오류율을 모델 × 함정 종류로 센다 (판정 불가 지점은 뺀다 - 고정 분석과 같다)
  3. C1 소유 변화 함정 오류를 규칙으로 나눈다 - R4(물건을 지니지 않은 쪽에게서 얻음), R6(지니지 않은 물건을 건넴 - 받는 단계 누락)
  4. 설정집에 기록한 항목 수와 속성 수, 라인마다 미리 정한 결과(goals)와 상태 변화(events) 수

    .venv/bin/python analysis/posthoc_discussion.py
"""
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from questline.lines import load_lines  # noqa: E402

MODELS = ["claude", "gemini", "gpt"]


def read(path: str) -> list[dict]:
    return [json.loads(x) for x in (ROOT / path).read_text().splitlines()]


cells = read("runs/questline/main/cells.jsonl") + read("runs/questline/selfcorrect_c4/cells.jsonl")
key = lambda vs: {(v.get("quest"), v["rule"]) for v in vs}  # noqa: E731
print("1. 재생성 뒤 실패한 셀 가운데 첫 출력과 같은 위반이 남은 셀 (모델별)")
for cond in ("C3", "C4"):
    out = []
    for m in MODELS:
        failed = [c for c in cells if c["condition"] == cond and c["model"] == m and len(c["attempts"]) > 1 and c["attempts"][-1]["violations"]]
        same = sum(bool(key(c["attempts"][0]["violations"]) & key(c["attempts"][-1]["violations"])) for c in failed)
        out.append(f"{m} {same}/{len(failed)} ({same / len(failed):.0%})")
    print(f"   {cond}: " + ", ".join(out))

scores = [r for r in read("runs/questline/main/scores.jsonl") if r["condition"] == "C1"]
err, tot, rule = Counter(), Counter(), Counter()
for r in scores:
    for pr in r["final_probes"].values():
        if pr["status"] == "undetermined":
            continue
        tot[(r["model"], pr["type"])] += 1
        if pr["status"] == "error":
            err[(r["model"], pr["type"])] += 1
            if pr["type"] == "custody":
                rule[(r["model"], "R4" if "R4" in pr["rules"] else "R6" if "R6" in pr["rules"] else "기타")] += 1
print("2. C1 함정 오류율 (판정 불가 제외)")
for m in MODELS:
    print(f"   {m}: " + ", ".join(f"{t} {err[(m, t)]}/{tot[(m, t)]} ({err[(m, t)] / tot[(m, t)]:.1%})" for t in ("custody", "death")))
print("3. C1 소유 변화 함정 오류의 규칙 (R4 가 있으면 R4 로 센다)")
for k in ("R4", "R6", "기타"):
    print(f"   {k}: " + ", ".join(f"{m} {rule[(m, k)]}" for m in MODELS) + f" | 합 {sum(rule[(m, k)] for m in MODELS)}")

wb = json.loads((ROOT / "worldbible/worldbible_v1.json").read_text())
ents = wb["entities"]
print(f"4. 설정집 항목 {len(ents)} ({dict(Counter(e['type'] for e in ents))}), 속성 {sum(len(e.get('attributes') or {}) for e in ents)}")
lines = load_lines(ROOT / "scenarios/questlines_v1.yaml")
goals = sum(len(q.get("goals") or []) for l in lines for q in l["quests"])
events = sum(len(l.get("events") or []) for l in lines)
print(f"   라인 {len(lines)}개: 미리 정한 결과 {goals}, 상태 변화 {events}, 합 {goals + events} "
      f"(라인당 {(goals + events) / len(lines):.1f}, 퀘스트당 {(goals + events) / sum(len(l['quests']) for l in lines):.1f})")
