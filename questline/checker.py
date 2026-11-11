"""규칙 검사기 - 퀘스트 라인을 설정집의 구조화 속성과 세계 상태로 판정한다.

라인의 퀘스트를 순서대로 읽으며 세계 상태(인물의 생사, 사물을 지닌 쪽)를 갱신하고 단계마다 규칙을 검사한다.

    R0  형식 - JSON 못 읽음, 행동이 일곱 가지 밖, 퀘스트 없음
    R1  설정집에 없는 이름, 종류가 다른 이름 (설정집 용어 - 지역, 화폐, 재료 - 는 통과)
    R2  죽은 인물과 대화, 받기, 전달, 처치 (조사, 찾기, 이동의 상대 칸에 둔 경우도)
    R3  인물을 거처가 아닌 곳에서 만남 (거처 "떠돌이"는 뺌, 안쪽 장소는 바깥 장소로 봄)
    R4  그 물건을 지니지 않은 쪽에게서 받음, 보관처가 아닌 곳에서 찾음 (이름 없는 인물에게서 받으면 장소로 판단, 장소를
        설정집 이름으로 정할 수 없으면 출처를 확인할 수 없어 위반)
    R5  출입 금지 장소 안, 봉인된 장소 안에서 찾거나 받음 ("<장소> 입구"는 밖)
    R6  플레이어가 지니지 않은 물건을 건넴
    R7  개요가 요구한 결과(hold, dead, met)를 이루지 않음

위반마다 kind 를 단다 - 라인 안에서 상태가 바뀐 인물이나 사물에 걸리면 "state", 아니면 "static".
상태는 개요가 정한 사건(events)으로도, 모델 출력의 단계(받기, 찾기, 전달, 처치)로도 바뀐다. 상태가 바뀐 엔티티로 표시하는
시점은 그 단계를 검사한 뒤라서, 같은 단계의 위반은 그 변화 때문에 state 가 되지 않는다.
R7 은 kind "goal" 로 따로 센다.

시점 규칙 (실험 상세 설계 부록 B):
- 개요가 정한 사건(events)의 at: start 는 그 퀘스트 단계를 검사하기 전에 적용한다
- 퀘스트 안에서 쓰러뜨린 인물은 퀘스트가 끝난 뒤 죽은 것으로 넣는다 (전리품 거두기 허용)
- goals 는 퀘스트 단계를 다 실행한 뒤, at: end 사건을 적용하기 전에 검사한다

설정집 v1 은 장소의 출입 제한(`출입`: 봉인 / 외부인 금지), 바깥 장소(`상위 장소`), 사본이 있는 곳(`사본 보관처`)을
속성 칸으로 갖는다. 그 칸이 설정집 어디에도 없으면(v0) 아래 V0_* 보충표를 쓴다 - v0 에서는 이 사실이 서술과 제약
문장에만 있었다(탐침 기록 analysis/probe_questline.md).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

ACTIONS = ("이동", "대화", "받기", "찾기", "전달", "처치", "조사")
MEET_ACTIONS = ("대화", "받기", "전달")
NO_RESIDENCE = {"떠돌이"}
ENTRANCE = re.compile(r"\s*입구(\s*밖)?$")

V0_PLACE_INSIDE = {"red_market": "tessal", "lantern_sanctum": "lindor"}
V0_ACCESS = {"black_well": "봉인", "stone_heart": "외부인 금지"}
V0_COPY_AT = {"treaty_scroll": {"lindor"}}

ACCESS_MSG = {
    "봉인": "{name} 은 봉인되어 있다 - 안에서 무엇을 찾거나 받을 수 없다",
    "외부인 금지": "{name} 은 외부인을 들이지 않는다 - 플레이어가 들어갈 수 없다",
}


def norm(s) -> str:
    return re.sub(r"\s+", "", s) if isinstance(s, str) else ""


def _as_list(v) -> list:
    if v is None:
        return []
    return list(v) if isinstance(v, (list, tuple)) else [v]


class Index:
    """설정집 색인 - 이름(별칭 포함)으로 엔티티를 찾고, 장소와 사물의 보충 속성을 모은다."""

    def __init__(self, wb: dict):
        self.ent = {e["id"]: e for e in wb["entities"]}
        self.by_name: dict[str, dict] = {}
        for e in wb["entities"]:
            for n in [e["name"], *(e.get("aliases") or [])]:
                self.by_name[norm(n)] = e
        for e in wb["entities"]:  # "<신분> <이름>", "<소속> <신분> <이름>", "<소속>의 <이름>", "<칭호> <이름>" - 개요와 모델이
            a = e.get("attributes") or {}  # 쓰는 표기. 검사기 안에서만 받고 설정집 별칭은 그대로 둔다
            if e["type"] != "character" or not a.get("신분"):
                continue
            heads = [a["신분"]] + ([f"{a['소속']} {a['신분']}", f"{a['소속']}의", a["소속"]] if a.get("소속") not in (None, "없음") else [])
            heads += [t["term"] for t in wb.get("terms") or [] if t["kind"] == "title" and e["name"] in t.get("description", "")]
            if a.get("거처") and a["거처"] not in NO_RESIDENCE:
                home = self.by_name.get(norm(a["거처"]))
                around = {a["거처"]}
                if home:
                    up = (home.get("attributes") or {}).get("상위 장소")
                    around |= {up} if up else set()
                    around |= {p["name"] for p in wb["entities"] if p["type"] == "place"
                               and norm((p.get("attributes") or {}).get("상위 장소")) == norm(a["거처"])}
                for pl in around:
                    heads += [f"{pl}의", f"{pl}의 {a['신분']}"]
                    if a.get("소속") not in (None, "없음"):
                        heads.append(f"{pl}의 {a['소속']} {a['신분']}")
            for n in [e["name"], *(e.get("aliases") or [])]:  # "<이름> <신분>"
                self.by_name.setdefault(norm(f"{n} {a['신분']}"), e)
            for h in heads:
                for n in [e["name"], *(e.get("aliases") or [])]:
                    self.by_name.setdefault(norm(f"{h} {n}"), e)
        self.terms: dict[str, str] = {}
        for t in wb.get("terms") or []:
            for n in [t["term"], *(t.get("aliases") or [])]:
                self.terms[norm(n)] = t["kind"]

        places = [e for e in wb["entities"] if e["type"] == "place"]
        objects = [e for e in wb["entities"] if e["type"] == "object"]
        if any("출입" in (e.get("attributes") or {}) for e in places):
            self.access = {e["id"]: e["attributes"]["출입"] for e in places if "출입" in (e.get("attributes") or {})}
        else:
            self.access = dict(V0_ACCESS)
        if any("상위 장소" in (e.get("attributes") or {}) for e in places):
            self.inside = {}
            for e in places:
                up = self.resolve((e.get("attributes") or {}).get("상위 장소"))
                if up:
                    self.inside[e["id"]] = up["id"]
        else:
            self.inside = dict(V0_PLACE_INSIDE)
        for inner_id, outer_id in self.inside.items():  # "<바깥 장소> <안쪽 장소>", "<바깥 장소>의 <안쪽 장소>" - 개요와 모델이
            inner, outer = self.ent.get(inner_id), self.ent.get(outer_id)  # 쓰는 표기("테살 항 붉은 시장")
            if not inner or not outer:
                continue
            for o in [outer["name"], *(outer.get("aliases") or [])]:
                for i in [inner["name"], *(inner.get("aliases") or [])]:
                    for form in (f"{o} {i}", f"{o}의 {i}"):
                        self.by_name.setdefault(norm(form), inner)
        if any("사본 보관처" in (e.get("attributes") or {}) for e in objects):
            self.copy_at = {}
            for e in objects:
                ids = {p["id"] for p in map(self.resolve, _as_list((e.get("attributes") or {}).get("사본 보관처"))) if p}
                if ids:
                    self.copy_at[e["id"]] = ids
        else:
            self.copy_at = {k: set(v) for k, v in V0_COPY_AT.items()}

    def resolve(self, name) -> dict | None:
        return self.by_name.get(norm(name)) if isinstance(name, str) and name else None

    def name(self, eid: str) -> str:
        return self.ent[eid]["name"]

    def within(self, place_id: str, home_id: str) -> bool:
        """place 가 home 이거나 home 안쪽인가."""
        seen = set()
        while place_id and place_id not in seen:
            if place_id == home_id:
                return True
            seen.add(place_id)
            place_id = self.inside.get(place_id)
        return False


@dataclass
class World:
    """세계 상태. holder 값은 ("npc", id) / ("faction", id) / ("place", id) / ("player",)."""

    dead: set[str] = field(default_factory=set)
    holder: dict[str, tuple] = field(default_factory=dict)
    place_of: dict[str, str] = field(default_factory=dict)  # 보관처 - 플레이어가 집거나 옮겨지면 지운다
    changed: set[str] = field(default_factory=set)  # 라인 안에서 상태가 바뀐 엔티티

    @classmethod
    def from_worldbible(cls, ix: Index) -> "World":
        w = cls()
        for e in ix.ent.values():
            a = e.get("attributes") or {}
            if e["type"] == "character" and a.get("died") is not None:
                w.dead.add(e["id"])
            if e["type"] != "object":
                continue
            owner, keeper = ix.resolve(a.get("소유자")), ix.resolve(a.get("보관처"))
            if owner and owner["type"] == "character":
                w.holder[e["id"]] = ("npc", owner["id"])
            elif owner and owner["type"] == "faction":
                w.holder[e["id"]] = ("faction", owner["id"])
            elif keeper:
                w.holder[e["id"]] = ("place", keeper["id"])
            if keeper:
                w.place_of[e["id"]] = keeper["id"]
        return w

    def apply(self, event: dict, ix: Index) -> None:
        """events 항목 하나 - {dead: id} 또는 {hold: [사물 id, "player" | 인물 id | 장소 id]}."""
        if "dead" in event:
            self.dead.add(event["dead"])
            self.changed.add(event["dead"])
        if "hold" in event:
            item, who = event["hold"]
            if who == "player":
                self.holder[item] = ("player",)
            else:
                kind = ix.ent[who]["type"]
                self.holder[item] = ("place", who) if kind == "place" else ("npc", who)
            self.place_of.pop(item, None)
            self.changed.add(item)


@dataclass
class QuestResult:
    violations: list[dict]
    met: set[str]
    killed: list[str]


def check_quest(q, ix: Index, w: World, qno: int = 1) -> QuestResult:
    """퀘스트 하나를 현재 세계 상태 w 위에서 판정하고, 퀘스트 안의 사물 이동과 처치를 w 에 반영한다."""
    v: list[dict] = []
    met: set[str] = set()
    killed: list[str] = []

    def add(rule, step, msg, ids=(), **extra):
        kind = "state" if any(i in w.changed for i in ids) else "static"
        v.append({"quest": qno, "step": step, "rule": rule, "kind": kind, "msg": msg, "entities": list(ids), **extra})

    if not isinstance(q, dict):
        add("R0", None, "퀘스트가 JSON 객체가 아니다")
        return QuestResult(v, met, killed)

    FIELD = {"의뢰인": "npc", "인물": "npc", "의뢰 장소": "place", "장소": "place", "사물": "item"}

    def ent(name, kind, step, field_name):
        if name in (None, "", "null"):
            return None
        if not isinstance(name, str):
            add("R0", step, f"{field_name} 칸 값이 문자열이 아니다", field=FIELD[field_name])
            return None
        e = ix.resolve(name)
        if e is None:
            tk = ix.terms.get(norm(name))
            if tk and ((kind == "place" and tk == "region") or (kind == "object" and tk in ("currency", "material"))):
                return None  # 설정집 용어 - 이름은 맞지만 상태를 따질 대상이 아니다
            add("R1", step, f"{field_name} '{name}' 은 설정집에 없는 이름이다", field=FIELD[field_name])
            return None
        if e["type"] != kind:
            add("R1", step, f"{field_name} '{name}' 은 설정집에서 {e['type']} 이다({kind} 이어야 한다)", field=FIELD[field_name])
            return None
        return e

    def place_ent(name, step, field_name):
        if isinstance(name, str) and ENTRANCE.search(name):
            return ent(ENTRANCE.sub("", name), "place", step, field_name), True
        return ent(name, "place", step, field_name), False

    def alive_here(npc, place, step):
        if npc["id"] in w.dead:
            add("R2", step, f"{npc['name']} 은 이미 죽었다", [npc["id"]])
            return
        home = (npc.get("attributes") or {}).get("거처")
        if place and home and home not in NO_RESIDENCE:
            h = ix.resolve(home)
            if h and not ix.within(place["id"], h["id"]):
                add("R3", step, f"{npc['name']} 의 거처는 {home} 인데 {place['name']} 에서 만나게 했다", [npc["id"]])

    def access(place, outside, step, act):
        if place is None or outside:
            return
        rule = ix.access.get(place["id"])
        if rule == "외부인 금지" or (rule == "봉인" and act in ("찾기", "받기")):
            add("R5", step, ACCESS_MSG[rule].format(name=place["name"]))

    def holder_text(item_id):
        h = w.holder.get(item_id)
        if not h:
            return "알 수 없음"
        return "플레이어" if h[0] == "player" else ix.name(h[1])

    def npc_holds(npc, item_id, place=None):
        h = w.holder.get(item_id)
        if h == ("npc", npc["id"]):
            return True
        na = npc.get("attributes") or {}
        if h and h[0] == "faction":
            f = ix.ent[h[1]]
            member = (f.get("attributes") or {}).get("수장") == npc["name"] or ix.resolve(na.get("소속")) is f
            keep = w.place_of.get(item_id)
            return member and (keep is None or (place is not None and ix.within(place["id"], keep)))
        home = ix.resolve(na.get("거처"))
        if h and h[0] == "place" and home and ix.within(h[1], home["id"]):
            return True
        if home and any(ix.within(home["id"], p) or ix.within(p, home["id"]) for p in ix.copy_at.get(item_id, ())):
            return True  # 사본이 있는 곳에 사는 인물은 사본을 건넬 수 있다
        return False

    def obtainable_at(place, item_id, via_unnamed=False):
        """인물을 거치지 않고 place 에서 item 을 얻을 수 있는가 - 보관처, 사본이 있는 곳, 이 퀘스트에서 쓰러뜨린 인물의 소지품.
        via_unnamed(이름 없는 인물에게서 받기)면 지닌 인물의 거처 안도 된다 - 그 집 사람이 건넨 것으로 본다."""
        h = w.holder.get(item_id)
        if via_unnamed and place is not None and h is not None and h[0] == "npc" and h[1] not in w.dead:
            home = ix.resolve((ix.ent[h[1]].get("attributes") or {}).get("거처"))
            if home and ix.within(place["id"], home["id"]):
                return True
        if h is not None and h[0] == "npc" and h[1] in killed:
            return True
        if place is None:
            return False  # 장소를 설정집 이름으로 정할 수 없으면 출처를 확인할 수 없다
        return ((h is not None and h[0] == "place" and ix.within(place["id"], h[1]))
                or (item_id in w.place_of and ix.within(place["id"], w.place_of[item_id]))
                or any(ix.within(place["id"], p) for p in ix.copy_at.get(item_id, ())))

    def where(place):
        return place["name"] if place else "정할 수 없는 곳"

    g = q.get("giver") or {}
    if not isinstance(g, dict):
        add("R0", -1, "의뢰인 칸이 JSON 객체가 아니다", field="npc")
        g = {}
    gnpc = ent(g.get("npc"), "character", -1, "의뢰인")
    gplace, gout = place_ent(g.get("place"), -1, "의뢰 장소")
    if gnpc:
        alive_here(gnpc, gplace, -1)
        met.add(gnpc["id"])
    access(gplace, gout, -1, "대화")

    steps = q.get("steps")
    if not isinstance(steps, list) or not steps:
        add("R0", None, "단계 목록이 없다")
        steps = []
    for i, s in enumerate(steps, start=1):
        if not isinstance(s, dict):
            add("R0", i, "단계가 JSON 객체가 아니다")
            continue
        act = s.get("action") if isinstance(s.get("action"), str) else ""
        act = act.strip()
        if act not in ACTIONS:
            add("R0", i, f"행동 '{s.get('action')}' 은 정해진 일곱 가지가 아니다", field="action")
        npc = ent(s.get("npc"), "character", i, "인물")
        place, outside = place_ent(s.get("place"), i, "장소")
        item = ent(s.get("item"), "object", i, "사물")
        access(place, outside, i, act)
        if npc and act in MEET_ACTIONS:
            alive_here(npc, place, i)
            met.add(npc["id"])
        elif npc and act != "처치" and npc["id"] in w.dead:
            add("R2", i, f"{npc['name']} 은 이미 죽었다", [npc["id"]], slot="other")  # 조사, 찾기, 이동의 상대 - 묻거나 주고받은 것은 아니다
        if npc and act == "처치":
            if npc["id"] in w.dead:
                add("R2", i, f"{npc['name']} 은 이미 죽었다", [npc["id"]])
            else:
                killed.append(npc["id"])
        if item and act == "받기":
            if npc and not npc_holds(npc, item["id"], place):
                add("R4", i, f"{npc['name']} 은 {item['name']} 을 건넬 수 없다(지닌 쪽: {holder_text(item['id'])})", [item["id"]])
            elif s.get("npc") in (None, "", "null") and not obtainable_at(place, item["id"], via_unnamed=True):  # 이름 없는 인물
                add("R4", i, f"{item['name']} 은 {where(place)} 에서 받을 수 없다(지닌 쪽: {holder_text(item['id'])})", [item["id"]])
            w.holder[item["id"]] = ("player",)
            w.place_of.pop(item["id"], None)  # 플레이어가 지닌 뒤에는 보관처에서 다시 찾을 수 없다
            w.changed.add(item["id"])
        if item and act == "찾기":
            if not obtainable_at(place, item["id"]):
                add("R4", i, f"{item['name']} 은 {where(place)} 에서 얻을 수 없다(지닌 쪽: {holder_text(item['id'])})", [item["id"]])
            w.holder[item["id"]] = ("player",)
            w.place_of.pop(item["id"], None)
            w.changed.add(item["id"])
        if item and act == "전달":
            if w.holder.get(item["id"]) != ("player",):
                add("R6", i, f"{item['name']} 을 플레이어가 지니지 않은 채 건네게 했다(지닌 쪽: {holder_text(item['id'])})", [item["id"]])
            if npc:
                w.holder[item["id"]] = ("npc", npc["id"])
                w.place_of.pop(item["id"], None)
                w.changed.add(item["id"])
    for k in killed:
        w.dead.add(k)
        w.changed.add(k)
    return QuestResult(v, met, killed)


def check_goals(goals: list[dict], res: QuestResult, ix: Index, w: World, qno: int) -> list[dict]:
    out = []
    for g in goals or []:
        if "hold" in g:
            item, who = g["hold"]
            want = ("player",) if who == "player" else (("place", who) if ix.ent[who]["type"] == "place" else ("npc", who))
            if w.holder.get(item) != want:
                got = w.holder.get(item)
                got_t = "알 수 없음" if not got else ("플레이어" if got[0] == "player" else ix.name(got[1]))
                want_t = "플레이어" if who == "player" else ix.name(who)
                out.append({"quest": qno, "step": None, "rule": "R7", "kind": "goal",
                            "msg": f"퀘스트가 끝났을 때 {ix.name(item)} 을 {want_t} 가 지녀야 하는데 {got_t} 가 지닌다", "entities": [item]})
        elif "dead" in g:
            if g["dead"] not in w.dead:
                out.append({"quest": qno, "step": None, "rule": "R7", "kind": "goal",
                            "msg": f"퀘스트에서 {ix.name(g['dead'])} 을 쓰러뜨려야 한다", "entities": [g["dead"]]})
        elif "met" in g:
            if g["met"] not in res.met:
                out.append({"quest": qno, "step": None, "rule": "R7", "kind": "goal",
                            "msg": f"퀘스트에서 {ix.name(g['met'])} 을 만나야 한다", "entities": [g["met"]]})
        else:
            raise ValueError(f"알 수 없는 goal 형식: {g}")
    return out


def _qno(v):
    """퀘스트 번호 - 1, "1", 1.0, "1번" 을 모두 1 로."""
    m = re.match(r"\s*(\d+)", str(v))
    return int(m.group(1)) if m else None


def _quest_for(quests: list, n: int):
    """n 번 퀘스트. 출력에 no 칸이 하나라도 있으면 번호로만 찾는다 - 가운데가 빠졌을 때 뒤 퀘스트를 밀려 읽지 않는다."""
    numbered = [x for x in quests if isinstance(x, dict) and "no" in x]
    if numbered:
        return next((x for x in numbered if _qno(x.get("no")) == n), None)
    return quests[n - 1] if len(quests) >= n else None


def check_line(line: dict, quests: list, ix: Index) -> list[dict]:
    """라인 정의(questline.lines 형식)와 모델 출력의 quests 목록을 받아 위반 목록을 돌려준다."""
    w = World.from_worldbible(ix)
    events = line.get("events") or []
    out: list[dict] = []
    for n, qdef in enumerate(line["quests"], start=1):
        for ev in events:
            if ev["quest"] == n and ev.get("at", "end") == "start":
                w.apply(ev, ix)
        q = _quest_for(quests if isinstance(quests, list) else [], n)
        if q is None:
            out.append({"quest": n, "step": None, "rule": "R0", "kind": "static", "msg": f"{n}번 퀘스트가 없다", "entities": []})
        else:
            res = check_quest(q, ix, w, qno=n)
            out += res.violations
            out += check_goals(qdef.get("goals"), res, ix, w, n)  # 빠진 퀘스트의 목표는 R0 하나로 센다
        for ev in events:
            if ev["quest"] == n and ev.get("at", "end") == "end":
                w.apply(ev, ix)
    return out


PROBE_RULES = {"custody": {"R4", "R6"}, "death": {"R2"}}


def probe_status(line: dict, quests, violations: list[dict], ix: Index) -> dict[int, str]:
    """함정 지점마다 "error"(상태 의존 오류), "kept"(지킴), "undetermined"(판정 불가) 가운데 하나.

    판정 불가로 두는 경우 - 지켰는지 틀렸는지 출력만으로 정할 수 없을 때다.
      - 소유 함정인데 앞 퀘스트에서 그 사물의 목표(R7)를 이미 못 이뤘다 - 세계 상태가 개요와 갈라져, 개요대로 해도
        뒤 함정에서 오류가 난다(같은 실수를 두 번 세지 않는다)
      - 함정의 전제가 출력에서 성립하지 않았다 - 앞 퀘스트가 빠졌는데 그 퀘스트가 이 사물이나 죽음을 다뤘다, 또는
        함정 퀘스트에서 목표 사물이 옮겨지지 않은 상태로 다뤄졌다(R4, R6 static)
      - 이 함정을 판단하는 단계(소유는 목표 사물을 다루는 단계, 죽음은 의뢰인과 상대가 있는 단계)에 형식 오류(R0)나
        이름 오류(R1)가 있다 - 누구에게서 무엇을 얻었는지 정할 수 없다(상태 의존 오류가 이미 잡혔으면 오류로 센다)
      - 죽음 함정인데 단계의 상대 칸에 설정집 인물이 하나도 없다 - 이름 없는 사람에게 묻거나 의뢰인 이름만 있다
      - 소유 함정인데 그 퀘스트의 목표 사물을 받기, 찾기, 전달 어느 단계에서도 다루지 않았다
      - 소유 함정에서 목표 사물을 이름 없는 인물에게서 받았다(지닌 인물의 거처 안이라 위반은 아니지만 누구에게서 받았는지
        정할 수 없다)
      - 죽음 함정인데 앞 퀘스트에서 그 인물을 쓰러뜨리라는 목표를 못 이뤘다, 오래전에 죽은 인물에게 물었다(R2 static),
        또는 죽은 인물을 조사, 찾기, 이동의 상대 칸에 두었다(R2 이지만 묻거나 주고받은 것은 아니라 함정 오류로 세지 않는다)
    """
    if not isinstance(quests, list):  # 출력 전체를 읽지 못했다(JSON 실패) - 어느 함정도 판정할 수 없다
        return {int(qn): "undetermined" for qn in (line.get("probes") or {})}
    violations = [x for x in violations if isinstance(x.get("quest"), int)]
    errs = probe_errors(line, violations)
    out = {}
    for qn, typ in (line.get("probes") or {}).items():
        qn = int(qn)
        q = _quest_for(quests if isinstance(quests, list) else [], qn)
        steps = [x for x in ((q.get("steps") or []) if isinstance(q, dict) else []) if isinstance(x, dict)]
        qv = [x for x in violations if x["quest"] == qn]
        goal_items = {g["hold"][0] for g in (line["quests"][qn - 1].get("goals") or []) if "hold" in g}
        before = [x for x in violations if x["quest"] < qn]
        # 함정의 전제(앞에서 바뀐 상태)가 출력에서 성립했는가
        if typ == "custody":
            involved = lambda m: any(  # noqa: E731
                ("hold" in g and g["hold"][0] in goal_items) for g in (line["quests"][m - 1].get("goals") or [])
            ) or any(ev["quest"] == m and "hold" in ev and ev["hold"][0] in goal_items for ev in line.get("events") or [])
            premise_broken = (any(x["rule"] == "R7" and goal_items & set(x["entities"]) for x in before)
                              or any(x["rule"] == "R4" or x["rule"] == "R6" for x in qv
                                     if x["kind"] == "static" and goal_items & set(x["entities"])))
        else:
            kill_goals = {g["dead"] for q0 in line["quests"][:qn - 1] for g in (q0.get("goals") or []) if "dead" in g}
            involved = lambda m: any("dead" in g for g in (line["quests"][m - 1].get("goals") or [])) or any(  # noqa: E731
                ev["quest"] == m and "dead" in ev for ev in line.get("events") or [])
            premise_broken = any(x["rule"] == "R7" and kill_goals & set(x["entities"]) for x in before)
        missing_before = any(x["rule"] == "R0" and x["step"] is None and x["entities"] == [] and involved(x["quest"])
                             and (_quest_for(quests if isinstance(quests, list) else [], x["quest"]) is None) for x in before)
        # 이 함정을 판단하는 칸 - 소유는 사물을 얻는 단계의 인물과 사물(인물이 없으면 장소), 건네는 단계의 사물.
        # 죽음은 의뢰인과 단계의 상대 칸. 다른 칸의 이름 오류는 판정에 쓰이지 않으므로 보지 않는다
        def act_of(x):
            a = x.get("action")
            return a.strip() if isinstance(a, str) else a

        def item_rel(x):
            e = ix.resolve(x.get("item"))
            return (e or {}).get("id") in goal_items or (e is None and x.get("item") not in (None, "", "null"))

        decides: dict[int, set] = {}
        if typ == "custody":
            for k, x in enumerate(steps, start=1):
                a = act_of(x)
                if a in ("받기", "찾기") or (a not in ACTIONS and item_rel(x)):
                    if item_rel(x) or a not in ACTIONS:
                        decides[k] = {"npc", "item", "action"} | ({"place"} if x.get("npc") in (None, "", "null") else set())
                elif a == "전달" and item_rel(x):
                    decides[k] = {"item"}
        else:
            decides[-1] = {"npc"}
            for k, x in enumerate(steps, start=1):
                if x.get("npc") not in (None, "", "null"):
                    decides[k] = {"npc", "action"}
        unreadable = any(x["rule"] in ("R0", "R1") and (x["step"] is None or x.get("field") in decides.get(x["step"], ()))
                         for x in qv)
        only_r6 = bool(errs.get(qn)) and all(x["rule"] == "R6" for x in errs[qn])
        if premise_broken or missing_before:
            out[qn] = "undetermined"
        elif errs.get(qn) and not (unreadable and only_r6):  # 읽지 못한 획득 단계 뒤의 R6 은 판정 불가
            out[qn] = "error"
        elif unreadable:
            out[qn] = "undetermined"
        elif typ == "death":
            named = any((ix.resolve(x.get("npc")) or {}).get("type") == "character" for x in steps)
            other_dead = any(x["rule"] == "R2" for x in qv)  # 오래전에 죽은 인물에게 묻거나, 죽은 인물을 조사 칸에 둠
            out[qn] = "kept" if named and not other_dead else "undetermined"
        else:
            touched = {(ix.resolve(x.get("item")) or {}).get("id") for x in steps if x.get("action") in ("받기", "찾기", "전달")}
            unnamed_get = any(x.get("action") == "받기" and x.get("npc") in (None, "", "null")
                              and (ix.resolve(x.get("item")) or {}).get("id") in goal_items for x in steps)
            out[qn] = "kept" if goal_items & touched and not unnamed_get else "undetermined"
    return out


def probe_errors(line: dict, violations: list[dict]) -> dict[int, list[dict]]:
    """함정 지점별 상태 의존 위반. {퀘스트 번호: [위반...]}. 지켰는지, 판정할 수 없는지는 probe_status 가 정한다."""
    out = {}
    for qn, typ in (line.get("probes") or {}).items():
        qn = int(qn)
        goal_items = {g["hold"][0] for g in (line["quests"][qn - 1].get("goals") or []) if "hold" in g}
        out[qn] = [x for x in violations
                   if x["quest"] == qn and x["kind"] == "state" and x["rule"] in PROBE_RULES[typ]
                   and not (typ == "death" and x.get("slot") == "other")
                   and not (typ == "custody" and goal_items and not goal_items & set(x["entities"]))]
    return out
