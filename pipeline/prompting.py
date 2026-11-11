"""생성 요청에 공통으로 들어가는 부분 - 닫힌 세계 지시, 시스템 역할, 설정집 텍스트.

설계 불변식(README): 모든 생성 요청에 닫힌 세계 지시를 동일하게 넣는다. 퀘스트 라인 요청은 questline.prompting 이
이 모듈의 세 가지를 조립한다. 이전 주제의 조건 정의(문맥 × 교정 2×2)와 요청 조립은 태그 lore-consistency-final 에 있다.
"""

from __future__ import annotations


CLOSED_WORLD_INSTRUCTION = (
    "아래 설정집에 정의된 인물, 지명, 사물, 사건만 사용한다. "
    "설정집에 없는 새 고유명사(인물, 지명, 조직, 유물 등)를 만들어 쓰지 않는다. "
    "설정집과 어긋나는 사실을 쓰지 않는다."
)

SYSTEM_ROLE = "당신은 판타지 RPG의 한국어 퀘스트, 대사 작가다."


def render_worldbible(wb: dict, entity_ids: set[str] | None = None) -> str:
    """world bible 을 모델이 읽을 설정집 텍스트로 편다.

    entity_ids 를 주면 그 엔티티와, 양끝이 모두 포함된 관계만 싣는다(이전 주제의 검색 조건용 - 퀘스트 라인 실험은 늘 전문을 싣는다).
    용어(terms), 제약, 화이트리스트는 조건과 무관하게 전부 싣는다 - 닫힌 세계 지시의 근거라서.
    """
    ids_by_entity = {e["id"]: e for e in wb["entities"]}
    chosen = [e for e in wb["entities"] if entity_ids is None or e["id"] in entity_ids]
    lines = [f"[세계] {wb['meta']['name']}", "", "[인물, 장소, 세력, 사물, 사건]"]
    for e in chosen:
        alias = f" (별칭: {', '.join(e['aliases'])})" if e.get("aliases") else ""
        attrs = ", ".join(f"{k}: {v}" for k, v in (e.get("attributes") or {}).items())
        attrs = f" [{attrs}]" if attrs else ""
        lines.append(f"- {e['name']}{alias} / {e['type']}{attrs}: {e['description']}")
    lines += ["", "[관계]"]
    for r in wb["relations"]:
        if entity_ids is not None and not ({r["subject"], r["object"]} <= entity_ids):
            continue
        s, o = ids_by_entity[r["subject"]]["name"], ids_by_entity[r["object"]]["name"]
        desc = f" - {r['description']}" if r.get("description") else ""
        lines.append(f"- {s} → {r['predicate']} → {o}{desc}")
    if wb.get("terms"):
        lines += ["", "[용어 - 세계, 지역, 종족, 시대, 화폐, 칭호]"]
        for t in wb["terms"]:
            alias = f" (별칭: {', '.join(t['aliases'])})" if t.get("aliases") else ""
            lines.append(f"- {t['term']}{alias} / {t['kind']}: {t['description']}")
    lines += ["", "[제약]"]
    for c in wb["constraints"]:
        lines.append(f"- ({c['kind']}) {c['statement']}")
    lines += ["", "[사용 가능한 고유명사 전체 목록]", ", ".join(wb["name_whitelist"])]
    return "\n".join(lines)
