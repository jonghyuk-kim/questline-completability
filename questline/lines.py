"""라인 정의 읽기와 형식 검사 (실험 상세 설계 부록 B).

    - id: M01
      giver: 세드릭 몰
      quests:
        - brief: ...                      # 모델이 받는 한 줄 개요
          goals: [{met: cedric}]          # 검사기만 보는 결과 (hold / dead / met)
      events:                             # 개요가 정한 상태 변화
        - {quest: 2, at: end, dead: veil} # at: start | end (생략하면 end)
        - {quest: 1, at: start, hold: [salt_ring, rosa]}
      probes: {4: death, 5: custody}      # 함정 지점
      death_answerers: [tovald]           # 죽음 함정에서 죽은 인물 대신 답할 산 인물 (부록 A 12)
      solution:                           # 모범 풀이 - 퀘스트마다 의뢰인 [인물, 장소] 와 단계 [행동, 인물, 장소, 사물]
        - giver: [세드릭 몰, 린도르]
          steps: [[대화, 세드릭 몰, 린도르, null]]

audit_line 은 라인 풀의 완료조건(실험 상세 설계 1-2)을 본다 - 모범 풀이가 위반 0 인지, 함정 지점이 실제로 함정인지
(소유 함정은 그 퀘스트에서 다루는 사물이 라인 안에서 설정집과 다른 쪽으로 옮겨져 있는지, 플레이어가 지닌 사물을 설정집
주인에게 건네는 함정 - 상태를 몰라도 맞힌다 - 이 아닌지, 죽음 함정은 그 앞에서 죽은 인물이 있는지), 함정 개요에 앞 행동을 떠올리게 하는 말이 없는지(부록 A 5), 같은 사물을 세 번 넘게 옮기지 않는지(부록 A 7),
죽음 함정의 대답자가 라인의 어느 개요에도 이름으로 나오지 않고 모범 풀이가 그 대답자를 찾아가는지(부록 A 12).
모델에게는 brief 만 보인다 - solution, death_answerers 도 goals 처럼 검사기와 점검 스크립트만 본다.
"""
from __future__ import annotations

from pathlib import Path

import yaml

from questline.checker import Index, World, check_line, check_quest

PROBE_TYPES = ("custody", "death")
PROBE_MIX = {"custody": 2, "death": 1}  # 실험 상세 설계 1-2 작업 3 - 라인마다 소유 함정 2, 죽음 함정 1
HINT_WORDS = ("다시", "원래", "돌려받", "돌려주", "돌려준")  # 부록 A 5 - 함정 개요에 쓰지 않는다
MAX_MOVES = 3  # 부록 A 7 - 같은 사물을 세 번 넘게 옮기지 않는다


def load_lines(path: str | Path) -> list[dict]:
    data = yaml.safe_load(Path(path).read_text())
    if not isinstance(data, list):
        raise ValueError(f"{path}: 라인 정의는 목록이어야 한다")
    for line in data:
        line["probes"] = {int(k): v for k, v in (line.get("probes") or {}).items()}
    return data


def validate_lines(lines: list[dict], ix: Index, probes_per_line: dict[str, int] | None = None) -> list[str]:
    """형식 문제 목록(빈 목록이면 통과). probes_per_line 을 주면 라인마다 함정 수가 그 값인지도 본다."""
    errs: list[str] = []
    seen = set()
    for line in lines:
        lid = line.get("id", "?")
        if lid in seen:
            errs.append(f"{lid}: id 가 겹친다")
        seen.add(lid)
        quests = line.get("quests") or []
        if not quests:
            errs.append(f"{lid}: quests 가 없다")
        if ix.resolve(line.get("giver")) is None:
            errs.append(f"{lid}: 의뢰인 '{line.get('giver')}' 이 설정집에 없다")
        for n, q in enumerate(quests, start=1):
            if not isinstance(q.get("brief"), str) or not q["brief"].strip():
                errs.append(f"{lid}-{n}: brief 가 없다")
            for g in q.get("goals") or []:
                errs += [f"{lid}-{n}: {e}" for e in _check_goal(g, ix)]
        for ev in line.get("events") or []:
            if not (1 <= ev.get("quest", 0) <= len(quests)):
                errs.append(f"{lid}: 사건 {ev} 의 quest 번호가 범위 밖이다")
            if ev.get("at", "end") not in ("start", "end"):
                errs.append(f"{lid}: 사건 {ev} 의 at 은 start 나 end 여야 한다")
            if "dead" in ev and ix.ent.get(ev["dead"], {}).get("type") != "character":
                errs.append(f"{lid}: 사건 {ev} 의 dead 는 인물 id 여야 한다")
            if "hold" in ev:
                errs += [f"{lid}: 사건 {e}" for e in _check_hold(ev["hold"], ix)]
            if "dead" not in ev and "hold" not in ev:
                errs.append(f"{lid}: 사건 {ev} 에 dead 나 hold 가 없다")
        probes = line.get("probes") or {}
        for qn, typ in probes.items():
            if typ not in PROBE_TYPES:
                errs.append(f"{lid}: 함정 종류 '{typ}' 은 custody 나 death 여야 한다")
            if not (1 <= int(qn) <= len(quests)):
                errs.append(f"{lid}: 함정 지점 {qn} 이 범위 밖이다")
        for a in line.get("death_answerers") or []:
            if ix.ent.get(a, {}).get("type") != "character":
                errs.append(f"{lid}: death_answerers 의 '{a}' 는 인물 id 여야 한다")
        if probes_per_line:
            for typ, want in probes_per_line.items():
                got = sum(1 for t in probes.values() if t == typ)
                if got != want:
                    errs.append(f"{lid}: {typ} 함정이 {got} 개다({want} 개여야 한다)")
    return errs


def _check_hold(hold, ix: Index) -> list[str]:
    if not (isinstance(hold, (list, tuple)) and len(hold) == 2):
        return [f"hold {hold} 는 [사물 id, 지닌 쪽] 이어야 한다"]
    item, who = hold
    errs = []
    if ix.ent.get(item, {}).get("type") != "object":
        errs.append(f"hold 의 '{item}' 은 사물 id 가 아니다")
    if who != "player" and ix.ent.get(who, {}).get("type") not in ("character", "place"):
        errs.append(f"hold 의 '{who}' 는 player, 인물 id, 장소 id 가운데 하나여야 한다")
    return errs


def _check_goal(g, ix: Index) -> list[str]:
    if not isinstance(g, dict) or len(g) != 1:
        return [f"goal {g} 는 hold, dead, met 가운데 하나만 가져야 한다"]
    (k, val), = g.items()
    if k == "hold":
        return _check_hold(val, ix)
    if k in ("dead", "met"):
        return [] if ix.ent.get(val, {}).get("type") == "character" else [f"goal {k} 의 '{val}' 은 인물 id 가 아니다"]
    return [f"goal 종류 '{k}' 은 hold, dead, met 가운데 하나여야 한다"]


def parse_probe_mix(text: str) -> dict[str, int] | None:
    """"custody=2,death=1" 을 사전으로. "none" 이면 None(함정 배분을 보지 않는다 - 시험 라인용)."""
    if text.strip().lower() == "none":
        return None
    out = {}
    for part in text.split(","):
        k, v = part.split("=")
        if k.strip() not in PROBE_TYPES:
            raise ValueError(f"함정 종류는 {PROBE_TYPES} 가운데 하나: {k}")
        out[k.strip()] = int(v)
    return out


def solution_quests(line: dict) -> list[dict]:
    """solution 을 모델 출력과 같은 quests 형식으로 편다."""
    out = []
    for n, q in enumerate(line.get("solution") or [], start=1):
        g = q.get("giver") or [None, None]
        steps = [{"action": a, "npc": npc, "place": place, "item": item, "desc": ""}
                 for a, npc, place, item in q.get("steps") or []]
        out.append({"no": n, "title": "", "giver": {"npc": g[0], "place": g[1]}, "steps": steps})
    return out


def name_forms(ent: dict) -> set[str]:
    """개요에서 그 인물을 가리키는 표기 - 이름, 별칭, 성을 뺀 이름."""
    names = {ent["name"], *(ent.get("aliases") or [])}
    names |= {n.split()[0] for n in list(names) if " " in n and n == ent["name"]}
    return names


def audit_line(line: dict, ix: Index) -> list[str]:
    """라인 하나의 완료조건 문제 목록(빈 목록이면 통과)."""
    lid = line.get("id", "?")
    sol = solution_quests(line)
    if len(sol) != len(line.get("quests") or []):
        return [f"{lid}: 모범 풀이의 퀘스트 수({len(sol)})가 개요 수({len(line.get('quests') or [])})와 다르다"]
    errs = [f"{lid}-{x['quest']}: 모범 풀이 위반 {x['rule']} - {x['msg']}" for x in check_line(line, sol, ix)]

    # 검사기와 같은 순서로 세계 상태를 따라가며 함정 지점 직전의 상태를 본다
    w = World.from_worldbible(ix)
    initial = dict(w.holder)
    history: dict[str, list] = {i: [h] for i, h in initial.items()}
    events = line.get("events") or []
    probes = line.get("probes") or {}

    def note_moves():
        for item, h in w.holder.items():
            if h != ("player",) and history.setdefault(item, [None])[-1] != h:
                history[item].append(h)

    for n, q in enumerate(sol, start=1):
        for ev in events:
            if ev["quest"] == n and ev.get("at", "end") == "start":
                w.apply(ev, ix)
        note_moves()
        typ = probes.get(n)
        if typ == "custody":
            touched = {ix.resolve(s["item"])["id"] for s in q["steps"]
                       if s["action"] in ("받기", "찾기", "전달") and ix.resolve(s["item"])}
            moved = {i for i in touched if i in w.changed and w.holder.get(i) != initial.get(i)}
            if not moved:
                errs.append(f"{lid}-{n}: 소유 함정인데 이 퀘스트에서 다루는 사물이 라인 안에서 옮겨진 것이 아니다")
            for g in line["quests"][n - 1].get("goals") or []:
                if "hold" not in g:
                    continue
                item, who = g["hold"]
                first = initial.get(item)
                owner_side = first == ("npc", who) or (
                    first is not None and first[0] == "faction" and who in ix.ent
                    and ix.resolve((ix.ent[who].get("attributes") or {}).get("소속")) is ix.ent.get(first[1]))
                stored = bool((ix.ent[item].get("attributes") or {}).get("보관처"))  # 보관처가 있으면 상태를 모르는 모델이 거기로 간다
                if w.holder.get(item) == ("player",) and owner_side and not stored:
                    errs.append(f"{lid}-{n}: 플레이어가 지닌 {ix.name(item)} 을 설정집 주인에게 건네는 함정이라 상태를 몰라도 "
                                f"맞힌다 - 받는 쪽을 주인이 아닌 인물로")
        elif typ == "death":
            if not (w.dead & w.changed):
                errs.append(f"{lid}-{n}: 죽음 함정인데 그 앞에서 죽은 인물이 없다")
            answerers = line.get("death_answerers") or []
            if not answerers:
                errs.append(f"{lid}-{n}: 죽음 함정인데 death_answerers 가 없다(부록 A 12)")
            for a in answerers:
                if a in w.dead:
                    errs.append(f"{lid}-{n}: 대답자 {ix.name(a)} 이 이미 죽었다")
                forms = name_forms(ix.ent.get(a, {"name": a}))
                for k, other in enumerate(line["quests"], start=1):
                    hit = sorted(f for f in forms if f in other["brief"])
                    if hit:
                        errs.append(f"{lid}-{k}: 죽음 함정 대답자 {ix.name(a)} 이 개요에 나온다({', '.join(hit)}) - "
                                    f"앞 개요에서 본 인물을 고르는 것만으로 맞히게 된다(부록 A 12)")
            talked = {e["id"] for s in q["steps"] if s["action"] == "대화" and (e := ix.resolve(s["npc"]))}
            if answerers and not talked & set(answerers):
                errs.append(f"{lid}-{n}: 모범 풀이의 죽음 함정 답이 death_answerers 가운데 누구도 아니다")
        if typ:
            brief = line["quests"][n - 1]["brief"]
            for word in HINT_WORDS:
                if word in brief:
                    errs.append(f"{lid}-{n}: 함정 개요에 '{word}' 를 썼다(부록 A 5)")
        check_quest(q, ix, w, qno=n)
        note_moves()
        for ev in events:
            if ev["quest"] == n and ev.get("at", "end") == "end":
                w.apply(ev, ix)
        note_moves()
    for item, hs in history.items():
        if len(hs) - 1 > MAX_MOVES:
            errs.append(f"{lid}: {ix.name(item)} 을 {len(hs) - 1} 번 옮겼다(부록 A 7 - {MAX_MOVES} 번까지)")
    return errs


def probe_distances(line: dict, ix: Index) -> dict[int, int | None]:
    """함정 지점마다 그 함정이 걸린 상태 변화와의 거리(함정 퀘스트 번호 − 상태가 바뀐 퀘스트 번호).

    모범 풀이로 세계 상태를 따라가며(audit_line 과 같은 순서) 함정 퀘스트의 단계를 보기 직전 상태를 쓴다.
    죽음 함정은 그때까지 라인 안에서 죽은 인물 가운데 가장 늦게 죽은 퀘스트, 소유 함정은 그 퀘스트가 받기, 찾기,
    전달로 다루는 사물 가운데 라인 안에서 옮겨진 것이 마지막으로 옮겨진 퀘스트를 쓴다(여럿이면 가장 가까운 것).
    퀘스트 시작에 일어난 사건(at: start)은 거리 0 이다. 상태 변화를 찾지 못하면 None.
    """
    sol = solution_quests(line)
    w = World.from_worldbible(ix)
    events = line.get("events") or []
    probes = line.get("probes") or {}
    died_at: dict[str, int] = {}
    moved_at: dict[str, int] = {}

    def mark(n: int, dead_before: set, holder_before: dict) -> None:
        for d in w.dead - dead_before:
            died_at[d] = n
        for item, h in w.holder.items():
            if holder_before.get(item) != h:
                moved_at[item] = n

    out: dict[int, int | None] = {}
    for n, q in enumerate(sol, start=1):
        for ev in events:
            if ev["quest"] == n and ev.get("at", "end") == "start":
                d0, h0 = set(w.dead), dict(w.holder)
                w.apply(ev, ix)
                mark(n, d0, h0)
        typ = probes.get(n)
        if typ == "death":
            out[n] = n - max(died_at.values()) if died_at else None
        elif typ == "custody":
            touched = {e["id"] for s in q["steps"]
                       if s["action"] in ("받기", "찾기", "전달") and (e := ix.resolve(s["item"]))}
            when = [moved_at[i] for i in touched if i in moved_at]
            out[n] = n - max(when) if when else None
        d0, h0 = set(w.dead), dict(w.holder)
        check_quest(q, ix, w, qno=n)
        for ev in events:
            if ev["quest"] == n and ev.get("at", "end") == "end":
                w.apply(ev, ix)
        mark(n, d0, h0)
    return out
