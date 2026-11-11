"""조건 실행 - 셀(라인 × 모델 × 조건 × 반복) 하나를 끝까지 생성한다.

    C1  단순 생성 - 한 번 생성해 그대로 채점
    C2  검사기 피드백 재생성 - 위반이 있으면 앞 출력과 위반 목록을 대화에 붙여 다시 생성 (최대 max_regen 회)
    C3  피드백 없는 재생성 - 위반이 있으면 처음 요청을 새 seed 로 다시 보냄 (최대 max_regen 회)
    C4  자기 수정 (본실험 뒤 더한 탐색 조건) - 위반이 있으면 앞 출력과 "진행할 수 없는 곳이 있다"는 통과 여부만 대화에
        붙여 다시 생성 (최대 max_regen 회). C2 와 멈추는 규칙, seed, 대화 구조가 같고 위반 목록만 없다

C1~C3 이 연구계획서의 조건(CONDITIONS)이고, C4 는 EXTRA_CONDITIONS 라 배치의 기본 조건에 들지 않는다.

seed 는 반복 r(1부터), 시도 t(첫 생성 0)에 42 + 100×(r−1) + t (seed_for).
client 는 chat(spec, messages, sampling, fetch_generation=...) 이 text, meta 속성을 가진 객체를 돌려주면 된다
(pipeline.generators.OpenRouterClient 와 그 Generation).
"""
from __future__ import annotations

from questline.checker import Index, check_line
from questline.prompting import build_messages, feedback_message, parse_quests, selfcheck_message

CONDITIONS = ("C1", "C2", "C3")
EXTRA_CONDITIONS = ("C4",)
ALL_CONDITIONS = CONDITIONS + EXTRA_CONDITIONS
SEED_BASE = 42
SEED_REP_STRIDE = 100


def seed_for(rep: int, attempt: int) -> int:
    """반복 rep(1부터), 시도 attempt(첫 생성 0)에 42 + 100×(rep−1) + attempt. 같은 seed 를 되풀이하지 않게 반복마다 100 씩 띄운다."""
    if rep < 1 or attempt < 0:
        raise ValueError(f"rep 는 1 이상, attempt 는 0 이상이어야 한다: rep={rep}, attempt={attempt}")
    return SEED_BASE + SEED_REP_STRIDE * (rep - 1) + attempt


def judge(line: dict, text: str, ix: Index, finish_reason: str | None = None) -> tuple[list | None, list[dict]]:
    """잘린 출력(finish_reason length)은 앞에 온전한 객체가 있어도 못 읽은 것으로 둔다 - 형식 실패로 센다."""
    quests = None if finish_reason == "length" else parse_quests(text)
    if quests is None:
        return None, [{"quest": None, "step": None, "rule": "R0", "kind": "static", "msg": "JSON 을 읽지 못했다", "entities": []}]
    return quests, check_line(line, quests, ix)


def run_cell(client, spec, wb: dict, ix: Index, line: dict, condition: str, rep: int,
             sampling: dict, max_regen: int = 2, fetch_generation: bool = True) -> dict:
    if condition not in ALL_CONDITIONS:
        raise ValueError(f"조건은 {ALL_CONDITIONS} 가운데 하나여야 한다: {condition}")
    first = build_messages(wb, line)
    msgs = first
    attempts = []
    for t in range(0, max_regen + 1):
        s = dict(sampling, seed=seed_for(rep, t))
        gen = client.chat(spec, msgs, s, fetch_generation=fetch_generation)
        quests, viol = judge(line, gen.text, ix, gen.meta.get("finish_reason"))
        attempts.append({"t": t, "seed": s["seed"], "text": gen.text, "quests": quests,
                         "violations": viol, "meta": gen.meta})
        if not viol or condition == "C1" or t == max_regen:
            break
        if condition == "C2":
            msgs = msgs + [{"role": "assistant", "content": gen.text},
                           {"role": "user", "content": feedback_message(viol)}]
        elif condition == "C4":  # 통과 여부만 - 위반 목록을 넣지 않는다
            msgs = msgs + [{"role": "assistant", "content": gen.text},
                           {"role": "user", "content": selfcheck_message()}]
        else:  # C3 - 앞 출력과 위반 사실을 넣지 않는다
            msgs = first
    return {"line_id": line["id"], "model": spec.name, "condition": condition, "rep": rep, "attempts": attempts}
