"""셀 하나의 채점 행 (실험 상세 설계 단계 2 작업 4).

마지막 출력(final_*)과 첫 출력(first_*)을 함께 남긴다. C2, C3 의 첫 출력은 C1 과 요청과 seed 가 같아 독립이 아니므로
RQ1 분석에는 넣지 않고 점검용으로만 쓴다(RQ1 은 C1 출력만). 함정 지점마다 status(error / kept / undetermined,
questline.checker.probe_status)를 남긴다 - 함정 오류율의 분모는 판정 불가를 뺀 함정 수다. 개요 결과 달성률은
goals_met / goals_total 이다 - 분모는 라인의 모든 결과, 출력에서 빠진 퀘스트와 읽지 못한 출력의 결과는 이루지 못한 것으로 센다.
"""
from __future__ import annotations

from collections import Counter

from questline.checker import _quest_for, probe_errors, probe_status

STATE_TYPE = {"R4": "wrong_source", "R6": "missing_acquire", "R2": "dead_npc"}


def _summary(line: dict, quests, violations: list[dict], ix) -> dict:
    probes = probe_errors(line, violations)
    status = probe_status(line, quests, violations, ix)
    state_types = Counter(STATE_TYPE[x["rule"]] for qn, errs in probes.items() if status[qn] == "error" for x in errs)
    steps = [len(q.get("steps") or []) for q in (quests or []) if isinstance(q, dict)]
    goals_total = sum(len(q.get("goals") or []) for q in line["quests"])
    goals_met = 0
    if isinstance(quests, list):
        for n, q in enumerate(line["quests"], start=1):
            if _quest_for(quests, n) is None:
                continue  # 빠진 퀘스트의 결과는 이루지 못한 것
            missed = sum(1 for x in violations if x["rule"] == "R7" and x.get("quest") == n)
            goals_met += max(len(q.get("goals") or []) - missed, 0)
    return {
        "completable": not violations,
        "n_violations": len(violations),
        "rules": sorted({x["rule"] for x in violations}),
        "static_violations": sum(1 for x in violations if x["kind"] == "static"),
        "goal_violations": sum(1 for x in violations if x["kind"] == "goal"),
        "probes": {str(qn): {"type": line["probes"][qn], "status": status[qn], "error": status[qn] == "error",
                             "rules": sorted({x["rule"] for x in errs}) if status[qn] == "error" else []}
                   for qn, errs in probes.items()},
        "state_error_types": dict(state_types),
        "steps_per_quest": (sum(steps) / len(steps)) if steps else None,
        "goals_total": goals_total,
        "goals_met": goals_met,
        "parsed": quests is not None,
    }


def score_cell(line: dict, cell: dict, ix) -> dict:
    atts = cell["attempts"]
    first, final = atts[0], atts[-1]
    cost = sum((a["meta"].get("usage") or {}).get("cost_usd") or 0.0 for a in atts)
    latency = sum(a["meta"].get("latency_ms") or 0 for a in atts) / 1000.0
    row = {k: cell[k] for k in ("line_id", "model", "condition", "rep")}
    row.update({
        "attempts": len(atts),
        "regenerations": len(atts) - 1,
        "cost_usd": cost,
        "latency_s": latency,
        "truncated": any(a["meta"].get("finish_reason") == "length" for a in atts),
    })
    row.update({f"final_{k}": v for k, v in _summary(line, final["quests"], final["violations"], ix).items()})
    row.update({f"first_{k}": v for k, v in _summary(line, first["quests"], first["violations"], ix).items()})
    return row
