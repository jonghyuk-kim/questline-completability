"""world bible 검증기 - 두 겹으로 검사한다.

1) 스키마 검증: schema.json(JSON Schema) 대비 형식 적합성.
2) 내적 정합성 스캔(실험 상세 설계 1-3의 규칙 기반 부분):
   - entities id 중복 없음
   - relations의 subject/object가 실존 entity id
   - name_whitelist가 entities의 name+aliases 와 terms의 term+aliases 합집합과 정확히 일치(누락/잉여 없음)
   - constraints id 중복 없음, terms term 중복 없음, 엔티티 이름과 용어가 겹치지 않음
   - 시간 순서: predicate 가 '이전에 일어났다' 인 관계는 양끝 사건의 attributes.year 가 그 순서여야 한다
   - 상태 속성 칸(규칙 검사기가 세계 상태로 읽는 칸): 거처, 보관처, 사본 보관처, 상위 장소는 장소 이름,
     소유자는 살아 있는 인물이나 세력 이름이어야 한다. 출입은 장소에만, 사본 보관처는 사물에만 둔다.
     상위 장소가 돌고 돌면 안 된다. v1 부터는 사물마다 소유자나 보관처가 하나 이상 있어야 한다
     (퀘스트 라인 실험의 설정집. v0 과 mini 픽스처는 이전 주제용이라 이 조건을 걸지 않는다)
   경고(실패 아님): relations description 누락, checkable_by=nli 제약의 nli_premise 누락, 관계가 하나도 없는
   고립 엔티티, 비슷한 이름 쌍. 앞의 셋은 이전 주제(NLI 판정, 검색)의 전제 품질 점검이라 지금 실험은 쓰지 않는다.

사용: python worldbible/validate.py [worldbible.json 경로]
      (기본값: worldbible/mini_worldbible.json)
"""

import json
import re
import sys
from pathlib import Path

import jsonschema

HERE = Path(__file__).parent
SCHEMA_PATH = HERE / "schema.json"


def check_integrity(wb: dict) -> list[str]:
    errors = []

    ids = [e["id"] for e in wb["entities"]]
    dup_ids = {i for i in ids if ids.count(i) > 1}
    if dup_ids:
        errors.append(f"entity id 중복: {sorted(dup_ids)}")
    id_set = set(ids)

    for i, r in enumerate(wb["relations"]):
        for side in ("subject", "object"):
            if r[side] not in id_set:
                errors.append(f"relations[{i}].{side} = '{r[side]}' 가 entities에 없음")

    declared = set(wb["name_whitelist"])
    actual = set(expected_whitelist(wb))
    missing = actual - declared
    extra = declared - actual
    if missing:
        errors.append(f"화이트리스트 누락(엔티티에는 있는데 목록에 없음): {sorted(missing)}")
    if extra:
        errors.append(f"화이트리스트 잉여(어느 엔티티에도 없음): {sorted(extra)}")

    cids = [c["id"] for c in wb["constraints"]]
    dup_cids = {i for i in cids if cids.count(i) > 1}
    if dup_cids:
        errors.append(f"constraint id 중복: {sorted(dup_cids)}")

    terms = [t["term"] for t in wb.get("terms", [])]
    dup_terms = {t for t in terms if terms.count(t) > 1}
    if dup_terms:
        errors.append(f"terms 중복: {sorted(dup_terms)}")
    entity_names = {e["name"] for e in wb["entities"]} | {a for e in wb["entities"] for a in e.get("aliases", [])}
    overlap = entity_names & set(terms)
    if overlap:
        errors.append(f"엔티티 이름과 용어가 겹침(한 이름은 한 곳에만): {sorted(overlap)}")

    by_id = {e["id"]: e for e in wb["entities"]}
    for i, r in enumerate(wb["relations"]):
        if r["predicate"] != BEFORE_PREDICATE:
            continue
        a, b = by_id.get(r["subject"]), by_id.get(r["object"])
        if not a or not b:
            continue
        ya, yb = (a.get("attributes") or {}).get("year"), (b.get("attributes") or {}).get("year")
        if ya is None or yb is None:
            errors.append(f"relations[{i}] '{BEFORE_PREDICATE}' 양끝에 attributes.year 가 없음: {r['subject']}, {r['object']}")
        elif not ya < yb:
            errors.append(f"relations[{i}] 시간 순서 모순: {a['name']}({ya}) 가 {b['name']}({yb}) 이전이어야 함")

    errors += check_state_attributes(wb)
    return errors


NO_RESIDENCE = {"떠돌이"}


def check_state_attributes(wb: dict) -> list[str]:
    """규칙 검사기(questline/checker.py)가 읽는 칸의 값이 설정집의 이름을 가리키는지 본다."""
    by_name = {}
    for e in wb["entities"]:
        for n in [e["name"], *e.get("aliases", [])]:
            by_name[n] = e

    def kind_of(name):
        e = by_name.get(name)
        return e["type"] if e else None

    m = re.match(r"v(\d+)", str(wb.get("meta", {}).get("version", "")))
    need_holder = bool(m) and int(m.group(1)) >= 1
    errors = []
    for e in wb["entities"]:
        a = e.get("attributes") or {}
        where = f"{e['id']}.attributes"
        home = a.get("거처")
        if e["type"] == "character" and home and home not in NO_RESIDENCE and kind_of(home) != "place":
            errors.append(f"{where}.거처 '{home}' 가 장소 이름이 아니다")
        if "출입" in a and e["type"] != "place":
            errors.append(f"{where}.출입 은 장소에만 둔다")
        up = a.get("상위 장소")
        if up is not None and (e["type"] != "place" or kind_of(up) != "place"):
            errors.append(f"{where}.상위 장소 '{up}' 는 장소에만 두고 장소 이름이어야 한다")
        if e["type"] == "object":
            owner, keeper = a.get("소유자"), a.get("보관처")
            if need_holder and owner is None and keeper is None:
                errors.append(f"{where} 에 소유자도 보관처도 없다")
            if owner is not None:
                o = by_name.get(owner)
                if o is None or o["type"] not in ("character", "faction"):
                    errors.append(f"{where}.소유자 '{owner}' 가 인물이나 세력 이름이 아니다")
                elif (o.get("attributes") or {}).get("died") is not None:
                    errors.append(f"{where}.소유자 '{owner}' 는 죽은 인물이다")
            if keeper is not None and kind_of(keeper) != "place":
                errors.append(f"{where}.보관처 '{keeper}' 가 장소 이름이 아니다")
            copies = a.get("사본 보관처")
            for c in ([copies] if isinstance(copies, str) else copies or []):
                if kind_of(c) != "place":
                    errors.append(f"{where}.사본 보관처 '{c}' 가 장소 이름이 아니다")
        elif "사본 보관처" in a:
            errors.append(f"{where}.사본 보관처 는 사물에만 둔다")

    parent = {e["id"]: by_name[(e.get("attributes") or {})["상위 장소"]]["id"]
              for e in wb["entities"]
              if e["type"] == "place" and kind_of((e.get("attributes") or {}).get("상위 장소")) == "place"}
    for start in parent:
        seen, cur = set(), start
        while cur in parent:
            if cur in seen:
                errors.append(f"상위 장소가 돌고 돈다: {start}")
                break
            seen.add(cur)
            cur = parent[cur]
    return errors


BEFORE_PREDICATE = "이전에 일어났다"


def expected_whitelist(wb: dict) -> list[str]:
    """엔티티 name+aliases 와 terms term+aliases 의 합집합 (world bible 순서 유지)."""
    out: list[str] = []
    for e in wb["entities"]:
        out.append(e["name"])
        out.extend(e.get("aliases", []))
    for t in wb.get("terms", []):
        out.append(t["term"])
        out.extend(t.get("aliases", []))
    seen = set()
    return [n for n in out if not (n in seen or seen.add(n))]


def _similar(a: str, b: str) -> bool:
    """비슷한 이름 쌍 - 문자 2-gram Jaccard >= 0.5 또는 앞 두 글자가 같고 길이가 같다."""
    a2 = {a[i:i + 2] for i in range(len(a) - 1)}
    b2 = {b[i:i + 2] for i in range(len(b) - 1)}
    if a2 and b2 and len(a2 & b2) / len(a2 | b2) >= 0.5:
        return True
    return len(a) == len(b) >= 3 and a[:2] == b[:2]


def warnings(wb: dict) -> list[str]:
    """실패는 아니지만 NLI 전제 품질에 걸리는 것."""
    out = []
    no_desc = [i for i, r in enumerate(wb["relations"]) if not r.get("description")]
    if no_desc:
        out.append(f"description 없는 관계 {len(no_desc)}건 (relations[{', '.join(map(str, no_desc))}]) - NLI 전제에서 빠진다")
    no_prem = [c["id"] for c in wb["constraints"] if c.get("checkable_by") == "nli" and not c.get("nli_premise")]
    if no_prem:
        out.append(f"nli_premise 없는 NLI 제약 {no_prem} - statement(규정문)가 전제로 쓰인다")
    linked = {r["subject"] for r in wb["relations"]} | {r["object"] for r in wb["relations"]}
    orphans = [e["id"] for e in wb["entities"] if e["id"] not in linked]
    if orphans:
        out.append(f"관계가 하나도 없는 고립 엔티티 {orphans} - RAG 관계 청크와 NLI 관계 전제에서 빠진다")
    names = [(e["id"], n) for e in wb["entities"] for n in [e["name"], *e.get("aliases", [])]]
    pairs = sorted({
        (a, b) for i, (ia, a) in enumerate(names) for ib, b in names[i + 1:] if ia != ib and _similar(a, b)
    })
    if pairs:
        out.append(f"비슷한 이름 쌍 {len(pairs)}건 (함정 층 T1 후보, 의도한 것인지 확인): {pairs}")
    return out


def name_like_unknowns(wb: dict) -> list[tuple[str, str]]:
    """제약 문장 안의 이름 꼴 토큰 중 화이트리스트에도 일반어 사전에도 없는 것 - 연구자 교차 검토 보조.
    형태소 분석기가 있으면 NNP 만 본다(없으면 건너뛴다)."""
    try:
        from kiwipiepy import Kiwi  # noqa: PLC0415
    except ImportError:
        return []
    kiwi = Kiwi()
    wl = set(wb["name_whitelist"])
    out = []
    for c in wb["constraints"]:
        text = f"{c['statement']} {c.get('nli_premise', '')}"
        for tok in kiwi.tokenize(text):
            if tok.tag == "NNP" and tok.form not in wl and not any(tok.form in w for w in wl):
                out.append((c["id"], tok.form))
    return out


def main() -> int:
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / "mini_worldbible.json"
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    wb = json.loads(target.read_text(encoding="utf-8"))

    try:
        jsonschema.validate(wb, schema)
    except jsonschema.ValidationError as e:
        print(f"[실패] 스키마 위반: {e.message} (경로: {'/'.join(map(str, e.absolute_path))})")
        return 1
    print("[통과] 스키마 검증")

    errors = check_integrity(wb)
    if errors:
        for msg in errors:
            print(f"[실패] 정합성: {msg}")
        return 1
    print("[통과] 내적 정합성 스캔")
    for msg in warnings(wb):
        print(f"[경고] {msg}")
    for cid, form in name_like_unknowns(wb):
        print(f"[확인] 제약 {cid} 에 화이트리스트 밖 고유명사 후보 '{form}' - 정의 안 된 이름이면 엔티티/용어에 추가")

    from collections import Counter  # noqa: PLC0415
    n_e, n_r, n_c = len(wb["entities"]), len(wb["relations"]), len(wb["constraints"])
    types = ", ".join(f"{k} {v}" for k, v in Counter(e["type"] for e in wb["entities"]).items())
    print(
        f"요약: {target.name} - 엔티티 {n_e} ({types}), 관계 {n_r} (밀도 {n_r / max(n_e, 1):.2f}/엔티티), "
        f"제약 {n_c}, 용어 {len(wb.get('terms', []))}, 화이트리스트 {len(wb['name_whitelist'])}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
