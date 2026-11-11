"""퀘스트 라인 생성 요청과 C2 피드백 메시지.

요청은 설정집 전문, 닫힌 세계 지시(pipeline.prompting 의 지시문 그대로), 라인 개요, 출력 형식을 한 메시지로 담는다.
출력 형식과 행동 규칙은 탐침 v2(scripts/probe_questline.py)와 같다 - 예비 실험과 비교할 수 있게 문구를 바꾸지 않는다.
"""
from __future__ import annotations

import json
import re

from pipeline.prompting import CLOSED_WORLD_INSTRUCTION, SYSTEM_ROLE, render_worldbible

STEP_SCHEMA = """{"action": "이동, 대화, 받기, 찾기, 전달, 처치, 조사 가운데 한 낱말", "npc": "상대 인물 이름 또는 null", "place": "그 단계가 일어나는 장소", "item": "주고받거나 찾는 사물 이름 또는 null", "desc": "한 줄 설명"}"""

RULES_TEXT = """규칙:
- npc, place, item 칸에는 설정집의 인물, 장소, 사물 이름(또는 별칭)만 쓴다. 이름 없는 물건(약초, 편지 등)이나 이름 없는 인물은 그 칸을 null 로 두고 desc 에 쓴다.
- 장소 밖에서 일어나는 일은 place 를 "<장소 이름> 입구" 로 쓴다.
- 단계는 플레이어가 실제로 하는 순서대로 쓴다. 모든 단계에 place 를 쓴다.
- 받기: npc 에게서 item 을 받는다. 찾기: place 에서 item 을 얻는다. 전달: npc 에게 item 을 건넨다. 처치: npc 를 쓰러뜨린다."""

LINE_FORMAT = f"""다음 JSON 하나만 출력한다. 코드 블록 표시나 설명을 붙이지 않는다.
{{"quests": [
  {{"no": 1, "title": "퀘스트 제목", "giver": {{"npc": "의뢰인 이름", "place": "의뢰하는 장소"}},
    "steps": [{STEP_SCHEMA}]}}
]}}
퀘스트마다 단계를 2~5개 쓴다. 각 퀘스트는 앞 퀘스트들의 결과가 반영된 세계에서 진행된다.
{RULES_TEXT}"""

TASK_HEAD = ("한 의뢰인에게서 시작해 이어지는 퀘스트 라인을 쓴다. 아래 개요의 퀘스트를 이 순서로, "
             "개요마다 퀘스트 하나씩 쓴다. 개요가 정하지 않은 인물, 장소, 사물은 설정집에서 골라 채운다.")


def build_messages(wb: dict, line: dict) -> list[dict]:
    briefs = "\n".join(f"{i}. {q['brief']}" for i, q in enumerate(line["quests"], start=1))
    user = "\n".join([
        "## 설정집", render_worldbible(wb), "",
        "## 지시", CLOSED_WORLD_INSTRUCTION, "",
        "## 과제 (quest line)", TASK_HEAD + "\n" + briefs, "",
        "## 출력 형식", LINE_FORMAT,
    ])
    return [{"role": "system", "content": SYSTEM_ROLE}, {"role": "user", "content": user}]


FEEDBACK_HEAD = "위 퀘스트 라인에는 플레이어가 실제로 진행할 수 없는 곳이 있다."
FEEDBACK_TAIL = "문제를 고쳐 같은 JSON 형식으로 퀘스트 라인 전체를 다시 출력한다. JSON 하나만 출력한다."


def feedback_message(violations: list[dict]) -> str:
    """C2 피드백 - 위반마다 퀘스트 번호, 단계, 이유(지금 지닌 쪽 포함) 한 줄."""
    lines = [FEEDBACK_HEAD + " 검사기가 찾은 문제:"]
    for x in violations:
        where = f"{x['quest']}번 퀘스트" if x.get("quest") else "퀘스트 라인"
        if x.get("step") == -1:
            where += " 의뢰인"
        elif x.get("step"):
            where += f" {x['step']}단계"
        lines.append(f"- {where}: {x['msg']}")
    lines.append(FEEDBACK_TAIL)
    return "\n".join(lines)


def selfcheck_message() -> str:
    """C4 자기 수정 - C2 피드백과 첫 문장과 끝 문장이 같고, 위반 목록 대신 스스로 찾으라는 한 문장만 있다."""
    return "\n".join([FEEDBACK_HEAD + " 어디가 문제인지 스스로 찾는다.", FEEDBACK_TAIL])


def split_json(text: str) -> tuple[object | None, str]:
    """모델 출력의 첫 { 에서 JSON 객체 하나를 읽어 (객체, 뒤에 남은 문자열) 을 돌려준다. 못 읽으면 (None, "").
    올바른 객체 뒤에 다른 문자열이 붙어도 객체는 읽는다(예비 측정 gpt 2건) - 붙은 문자열은 집계에서 따로 센다."""
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", (text or "").strip())
    i = t.find("{")
    if i < 0:
        return None, ""
    try:
        d, end = json.JSONDecoder().raw_decode(t, i)
    except json.JSONDecodeError:
        return None, ""
    return d, t[end:].strip()


def parse_quests(text: str) -> list | None:
    """모델 출력에서 quests 목록을 꺼낸다. 못 읽으면 None."""
    d, _ = split_json(text)
    q = d.get("quests") if isinstance(d, dict) else None
    return q if isinstance(q, list) else None
