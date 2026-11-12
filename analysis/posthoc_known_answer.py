"""사후 확인 (미리 정한 분석 아님, 2026-11-12 논문 수정 과정에서 더함) - 정답이 정해진 풀이로 검사기 판정을 확인한다.

사람이 판정하지 않아도 정답을 아는 풀이가 있다.
  1. 통과해야 하는 풀이 - 라인마다 연구자가 정한 모범 풀이(solution). 오류가 없고 함정 지점이 모두 통과(kept)여야 한다
  2. 잡혀야 하는 풀이 - 모범 풀이의 함정 지점 하나에 상태 변화를 반영하지 않은 단계를 넣은 풀이. 그 지점이 오류(error)이고
     기대한 규칙의 상태 의존 오류가 그 퀘스트에 있어야 한다
     가. 소유 변화 함정, 옛 소유자 - 물건을 받는 단계의 상대를 라인이 시작할 때의 소유자로 바꾼다 (기대 R4)
     나. 소유 변화 함정, 되찾기 누락 - 물건을 받거나 찾는 단계를 빼고 건네는 단계만 남긴다 (기대 R6)
     다. 죽음 함정 - 대답할 인물과 만나는 단계의 상대를 사망한 인물로 바꾼다 (기대 R2)
넣을 수 없는 경우(예: 모범 풀이에 받는 단계가 없다, 처음 소유자가 지금 소유자와 같다)는 세지 않고 수만 적는다.

모델 출력이 아니라 모범 풀이를 고친 것이므로, 모델이 낸 글에서 생기는 표기 차이나 규칙 밖 오류는 이 확인의 범위가 아니다.

    .venv/bin/python analysis/posthoc_known_answer.py
"""
import copy
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from questline.checker import Index, World, check_line, check_quest, probe_status  # noqa: E402
from questline.lines import load_lines, solution_quests  # noqa: E402

ix = Index(json.loads((ROOT / "worldbible/worldbible_v1.json").read_text()))
POOLS = {"본 실험 40": "scenarios/questlines_v1.yaml", "예비 측정 6": "scenarios/questlines_pre.yaml"}
EXPECT = {"옛 소유자": "R4", "되찾기 누락": "R6", "사망 인물": "R2"}


def home(cid: str) -> str | None:
    return (ix.ent[cid].get("attributes") or {}).get("거처")


def holder_before(line: dict, sol: list, n: int, item: str):
    """퀘스트 n 을 시작할 때 item 을 지닌 쪽 - 검사기와 같은 순서로 모범 풀이를 따라간다."""
    w = World.from_worldbible(ix)
    events = line.get("events") or []
    for m in range(1, n + 1):
        for ev in events:
            if ev["quest"] == m and ev.get("at", "end") == "start":
                w.apply(ev, ix)
        if m == n:
            return w.holder.get(item)
        check_quest(sol[m - 1], ix, w, qno=m)
        for ev in events:
            if ev["quest"] == m and ev.get("at", "end") == "end":
                w.apply(ev, ix)


def judge(line: dict, quests: list, n: int):
    v = check_line(line, quests, ix)
    st = probe_status(line, quests, v, ix)[n]
    rules = {x["rule"] for x in v if x["quest"] == n and x["kind"] == "state"}
    return st, rules


def mutations(line: dict, sol: list, n: int, typ: str):
    """(이름, 고친 풀이) 또는 (이름, None - 넣을 수 없음) 을 낸다."""
    q = sol[n - 1]
    if typ == "custody":
        item = next(g["hold"][0] for g in line["quests"][n - 1]["goals"] if "hold" in g)
        iname = ix.name(item)
        is_item = lambda s: (ix.resolve(s.get("item")) or {}).get("id") == item  # noqa: E731
        gets = [k for k, s in enumerate(q["steps"]) if s["action"] in ("받기", "찾기") and is_item(s)]
        gives = [k for k, s in enumerate(q["steps"]) if s["action"] == "전달" and is_item(s)]
        first = World.from_worldbible(ix).holder.get(item)
        now = holder_before(line, sol, n, item)
        recv = [k for k in gets if q["steps"][k]["action"] == "받기"]
        if recv and first and first[0] == "npc" and first != now and home(first[1]):
            m = copy.deepcopy(sol)
            m[n - 1]["steps"][recv[0]].update(npc=ix.name(first[1]), place=home(first[1]), item=iname)
            yield "옛 소유자", m
        else:
            yield "옛 소유자", None
        if gets and gives and min(gets) < max(gives):
            m = copy.deepcopy(sol)
            m[n - 1]["steps"] = [s for k, s in enumerate(q["steps"]) if k not in gets]
            yield "되찾기 누락", m
        else:
            yield "되찾기 누락", None
    else:
        dead = [e["dead"] for e in (line.get("events") or []) if "dead" in e and e["quest"] < n]
        dead += [g["dead"] for qd in line["quests"][:n - 1] for g in (qd.get("goals") or []) if "dead" in g]
        answerers = set(line.get("death_answerers") or [])
        talk = [k for k, s in enumerate(q["steps"]) if (ix.resolve(s.get("npc")) or {}).get("id") in answerers]
        if dead and talk and home(dead[0]):
            m = copy.deepcopy(sol)
            m[n - 1]["steps"][talk[0]].update(npc=ix.name(dead[0]), place=home(dead[0]))
            yield "사망 인물", m
        else:
            yield "사망 인물", None


for pool, path in POOLS.items():
    lines = load_lines(ROOT / path)
    ok_lines = ok_probes = n_probes = 0
    made, caught, skipped, missed = Counter(), Counter(), Counter(), []
    for line in lines:
        sol = solution_quests(line)
        v = check_line(line, sol, ix)
        st = probe_status(line, sol, v, ix)
        ok_lines += not v
        n_probes += len(st)
        ok_probes += sum(s == "kept" for s in st.values())
        for n, typ in sorted((int(k), t) for k, t in line["probes"].items()):
            for name, m in mutations(line, sol, n, typ):
                if m is None:
                    skipped[name] += 1
                    continue
                made[name] += 1
                status, rules = judge(line, m, n)
                if status == "error" and EXPECT[name] in rules:
                    caught[name] += 1
                else:
                    missed.append((line["id"], n, name, status, sorted(rules)))
    print(f"[{pool}]")
    print(f"  모범 풀이: 오류 없는 라인 {ok_lines}/{len(lines)}, 통과로 판정된 함정 지점 {ok_probes}/{n_probes}")
    for name in EXPECT:
        print(f"  {name}({EXPECT[name]}): 넣은 풀이 {made[name]}, 그 지점을 기대한 규칙의 오류로 판정 {caught[name]}, 넣을 수 없음 {skipped[name]}")
    print(f"  합계: 넣은 풀이 {sum(made.values())}, 검출 {sum(caught.values())}")
    for x in missed:
        print("  검출하지 못함:", x)
