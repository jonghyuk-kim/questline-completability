"""퀘스트 라인 실험의 오프라인 테스트 - 검사기 시험 묶음(실험 상세 설계 1-3), 조건 실행, 라인 형식, 채점.

검사기 시험 묶음은 정상 라인(모범 풀이)이 위반 0 이고, 규칙마다 오류 하나를 심은 라인이 정확히 그 규칙으로,
기대한 kind(state / static / goal)로 잡히는지 본다. 시험 묶음은 설정집 v0 과 v1 으로 한 번씩 돈다 - 모듈 전역 IX 를 쓰는
시험은 pytest_generate_tests 가 두 판으로 나눠 돌린다(시험 묶음 v1, 실험 상세 설계 1-3). 라인 풀(본실험 40, 예비 측정 6)은
모범 풀이가 위반 0 인지 본다.
"""
from __future__ import annotations

import copy
import inspect
import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from questline.checker import V0_ACCESS, V0_COPY_AT, V0_PLACE_INSIDE, Index, check_line, probe_errors
from questline.lines import PROBE_MIX, audit_line, load_lines, parse_probe_mix, solution_quests, validate_lines
from questline.prompting import build_messages, parse_quests, split_json
from questline.run import judge, run_cell
from questline.score import score_cell

ROOT = Path(__file__).resolve().parents[1]
WB = json.loads((ROOT / "worldbible" / "worldbible_v0.json").read_text())
IX = Index(WB)
SUITE_IX = {"v0": IX, "v1": Index(json.loads((ROOT / "worldbible" / "worldbible_v1.json").read_text()))}


def pytest_generate_tests(metafunc):
    """모듈 전역 IX 를 쓰는 시험(검사기 시험 묶음)은 설정집 v0, v1 으로 한 번씩 돌린다."""
    if metafunc.function.__module__ == __name__ and re.search(r"\bIX\b|\bstatus\(", inspect.getsource(metafunc.function)):
        metafunc.parametrize("worldbible", sorted(SUITE_IX), indirect=True)


@pytest.fixture(autouse=True)
def worldbible(request, monkeypatch):
    version = getattr(request, "param", "v0")
    monkeypatch.setitem(globals(), "IX", SUITE_IX[version])
    return version


def S(action, npc=None, place=None, item=None):
    return {"action": action, "npc": npc, "place": place, "item": item, "desc": ""}


def Q(no, steps, giver=("세드릭 몰", "린도르")):
    return {"no": no, "title": f"q{no}", "giver": {"npc": giver[0], "place": giver[1]}, "steps": steps}


# 형제단 라인 - 2번 퀘스트 끝에 베일이 죽고(플레이어가 쓰러뜨림) 가면을 플레이어가 거두며, 3번에서 미르나에게 맡긴다.
LINE = {
    "id": "T01", "giver": "세드릭 몰",
    "quests": [
        {"brief": "세드릭 몰이 잔당의 소굴을 찾아 달라고 한다.", "goals": [{"met": "cedric"}]},
        {"brief": "잿돌 요새에서 베일을 쓰러뜨리고 가면을 거둔다.", "goals": [{"dead": "veil"}, {"hold": ["dargo_mask", "player"]}]},
        {"brief": "가면을 린도르의 미르나에게 맡긴다.", "goals": [{"hold": ["dargo_mask", "mirna"]}]},
        {"brief": "형제단의 비밀을 아는 사람에게 이야기를 듣는다.", "goals": []},
        {"brief": "다르고의 가면을 벤토 사르에게 넘긴다.", "goals": [{"hold": ["dargo_mask", "bento"]}]},
    ],
    "events": [],
    "probes": {4: "death", 5: "custody"},
}


def good_quests():
    return [
        Q(1, [S("대화", "세드릭 몰", "린도르"), S("조사", None, "잿돌 요새")]),
        Q(2, [S("처치", "베일", "잿돌 요새"), S("찾기", None, "잿돌 요새", "다르고의 가면")]),
        Q(3, [S("전달", "미르나", "린도르", "다르고의 가면")]),
        Q(4, [S("대화", "하렌드 발크", "서리 관문")]),
        Q(5, [S("받기", "미르나", "린도르", "다르고의 가면"), S("전달", "벤토 사르", "테살 항", "다르고의 가면")]),
    ]


def only(viol):
    assert len(viol) == 1, viol
    return viol[0]


# ---- 검사기 시험 묶음 -------------------------------------------------------------

def test_good_line_passes():
    assert check_line(LINE, good_quests(), IX) == []


def test_r0_bad_action():
    qs = good_quests()
    qs[3]["steps"][0]["action"] = "조사 중"
    x = only(check_line(LINE, qs, IX))
    assert (x["rule"], x["kind"], x["quest"]) == ("R0", "static", 4)


def test_r0_missing_quest():
    x = only(check_line(LINE, good_quests()[:4], IX))
    assert (x["rule"], x["quest"]) == ("R0", 5)


def test_r1_unknown_name():
    qs = good_quests()
    qs[3]["steps"][0]["place"] = "용의 둥지"
    x = only(check_line(LINE, qs, IX))
    assert (x["rule"], x["kind"]) == ("R1", "static")


def test_r1_terms_pass():
    qs = good_quests()
    qs[3]["steps"].append(S("이동", None, "회색 고원"))
    qs[3]["steps"].append(S("찾기", None, "서리 관문", "은잎"))
    assert check_line(LINE, qs, IX) == []


def test_r2_dead_npc_state():
    qs = good_quests()
    qs[3]["steps"] = [S("대화", "베일", "잿돌 요새")]
    x = only(check_line(LINE, qs, IX))
    assert (x["rule"], x["kind"]) == ("R2", "state")
    assert probe_errors(LINE, [x]) == {4: [x], 5: []}


def test_r2_dead_in_worldbible_is_static():
    qs = good_quests()
    qs[3]["steps"] = [S("대화", "다르고", "잿돌 골짜기")]
    x = only(check_line(LINE, qs, IX))
    assert (x["rule"], x["kind"]) == ("R2", "static")
    assert probe_errors(LINE, [x])[4] == []  # 라인 안에서 바뀐 상태가 아니라 함정 오류가 아니다


def test_r3_location():
    qs = good_quests()
    qs[3]["steps"] = [S("대화", "하렌", "테살 항")]
    x = only(check_line(LINE, qs, IX))
    assert (x["rule"], x["kind"]) == ("R3", "static")


def test_r3_inner_place_and_wanderer_pass():
    qs = good_quests()
    qs[3]["steps"] = [S("대화", "미르네", "붉은 시장"), S("대화", "오렌 케이", "서리 관문")]
    assert check_line(LINE, qs, IX) == []


def test_r4_wrong_source_state():
    qs = good_quests()
    qs[4]["steps"][0] = S("받기", "세드릭 몰", "린도르", "다르고의 가면")
    x = only(check_line(LINE, qs, IX))
    assert (x["rule"], x["kind"]) == ("R4", "state")
    assert probe_errors(LINE, [x])[5] == [x]


def test_r4_static_wrong_source():
    qs = good_quests()
    qs[3]["steps"] = [S("받기", "하렌", "달빛 나루", "새벽의 검"), S("전달", "하렌드 발크", "서리 관문", "새벽의 검")]
    x = only(check_line(LINE, qs, IX))
    assert (x["rule"], x["kind"]) == ("R4", "static")


def test_r4_copy_and_keeper_pass():
    qs = good_quests()
    qs[3]["steps"] = [S("받기", "카일라 브란", "린도르", "첫 서리 조약문"),
                      S("찾기", None, "하얀 절벽 수도원", "새벽의 종")]
    assert check_line(LINE, qs, IX) == []


def test_r5_no_entry_and_entrance():
    qs = good_quests()
    qs[3]["steps"] = [S("대화", "툰가르", "돌의 심장")]
    x = only(check_line(LINE, qs, IX))
    assert (x["rule"], x["kind"]) == ("R5", "static")
    qs[3]["steps"] = [S("대화", "툰가르", "돌의 심장 입구")]
    assert check_line(LINE, qs, IX) == []


def test_r5_sealed_find():
    qs = good_quests()
    qs[3]["steps"] = [S("조사", None, "검은 우물")]
    assert check_line(LINE, qs, IX) == []  # 봉인된 곳도 살펴보는 것은 된다
    qs[3]["steps"] = [S("찾기", None, "검은 우물", "검은 우물의 인장")]
    rules = sorted(x["rule"] for x in check_line(LINE, qs, IX))
    assert rules == ["R4", "R5"]  # 봉인 안에서 찾음 + 인장은 미르나가 지님


def test_r6_missing_acquire_state():
    qs = good_quests()
    qs[4]["steps"] = [S("전달", "벤토 사르", "테살 항", "다르고의 가면")]
    x = only(check_line(LINE, qs, IX))
    assert (x["rule"], x["kind"]) == ("R6", "state")
    assert "미르나" in x["msg"]


def test_r7_goal_not_met():
    qs = good_quests()
    qs[4]["steps"][1] = S("전달", "세드릭 몰", "린도르", "다르고의 가면")
    x = only(check_line(LINE, qs, IX))
    assert (x["rule"], x["kind"], x["quest"]) == ("R7", "goal", 5)


def test_r7_dropping_steps_is_caught():
    qs = good_quests()
    qs[4]["steps"] = [S("이동", None, "테살 항")]  # 단계를 빼서 R4, R6 을 피한 출력
    x = only(check_line(LINE, qs, IX))
    assert x["rule"] == "R7"


def test_loot_from_killed_npc():
    qs = good_quests()
    qs[1]["steps"] = [S("처치", "베일", "잿돌 요새"), S("받기", "베일", "잿돌 요새", "다르고의 가면")]
    assert check_line(LINE, qs, IX) == []  # 쓰러뜨린 인물은 퀘스트가 끝난 뒤 죽은 것으로 넣는다


def test_cannot_find_again_at_storage_after_pickup():
    qs = good_quests()
    qs[2]["steps"] = [S("찾기", None, "잿돌 요새", "다르고의 가면"), S("전달", "미르나", "린도르", "다르고의 가면")]
    x = only(check_line(LINE, qs, IX))  # 2번에서 이미 거둔 가면을 요새에서 또 찾는다
    assert (x["rule"], x["kind"], x["quest"]) == ("R4", "state", 3)


def test_receive_from_unnamed_npc_uses_place_rule():
    qs = good_quests()
    qs[4]["steps"][0] = S("받기", None, "테살 항", "다르고의 가면")  # 미르나가 지닌 가면을 미르나의 거처 밖에서 이름 없는 사람에게
    x = only(check_line(LINE, qs, IX))
    assert (x["rule"], x["kind"], x["quest"]) == ("R4", "state", 5)
    qs = good_quests()
    qs[3]["steps"] = [S("받기", None, "하얀 절벽 수도원", "새벽의 종")]  # 보관처에서 이름 없는 수도사에게서 받음
    assert check_line(LINE, qs, IX) == []


def test_dead_npc_in_any_slot_is_r2():
    qs = good_quests()
    qs[3]["steps"] = [S("조사", "베일", "잿돌 요새")]
    x = only(check_line(LINE, qs, IX))
    assert (x["rule"], x["kind"], x["quest"]) == ("R2", "state", 4)


def test_find_without_resolvable_place_is_r4():
    qs = good_quests()
    qs[4]["steps"][0] = S("찾기", None, "강의 땅", "다르고의 가면")  # 지역 용어 - 장소를 정할 수 없다
    x = only(check_line(LINE, qs, IX))
    assert (x["rule"], x["kind"], x["quest"]) == ("R4", "state", 5)
    qs[4]["steps"][0] = S("찾기", None, None, "다르고의 가면")
    assert only(check_line(LINE, qs, IX))["rule"] == "R4"


def status(qs, line=LINE, ix=None):
    from questline.checker import probe_status
    ix = ix or IX
    return probe_status(line, qs, check_line(line, qs, ix), ix)


def test_probe_status_kept_and_error():
    assert status(good_quests()) == {4: "kept", 5: "kept"}
    qs = good_quests()
    qs[3]["steps"] = [S("대화", "베일", "잿돌 요새")]
    assert status(qs)[4] == "error"


def test_death_probe_without_named_contact_is_undetermined():
    qs = good_quests()
    qs[3]["steps"] = [S("대화", None, "서리 관문")]  # 의뢰인 이름은 있지만 이름 없는 사람에게 묻는다
    assert status(qs)[4] == "undetermined"
    qs[3]["steps"] = [S("대화", "고원 수호자 장군 베일", "잿돌 요새")]  # 이름을 못 알아봄 - R1 만 나고 판정 불가
    assert status(qs)[4] == "undetermined"


def test_missing_middle_quest_does_not_shift_later_quests():
    qs = [q for q in good_quests() if q["no"] != 3]  # 3번을 빠뜨림
    v = check_line(LINE, qs, IX)
    assert [(x["rule"], x["quest"]) for x in v if x["quest"] == 3] == [("R0", 3)]
    assert not [x for x in v if x["quest"] == 4]  # 4번은 4번 출력으로 채점한다


def test_unnamed_attendant_at_holder_home_passes_but_probe_undetermined():
    qs = good_quests()
    qs[4]["steps"][0] = S("받기", None, "린도르", "다르고의 가면")  # 미르나의 거처에서 시종에게
    assert check_line(LINE, qs, IX) == []
    assert status(qs)[5] == "undetermined"


def test_death_probe_old_dead_or_failed_kill_is_undetermined():
    qs = good_quests()
    qs[3]["steps"] = [S("대화", "다르고", "잿돌 골짜기")]  # 오래전에 죽은 인물 - R2 static
    assert status(qs)[4] == "undetermined"
    qs = good_quests()
    qs[1]["steps"] = [S("찾기", None, "잿돌 요새", "다르고의 가면")]  # 베일을 쓰러뜨리지 않음 - 2번 R7
    qs[3]["steps"] = [S("대화", "베일", "잿돌 요새")]
    assert status(qs)[4] == "undetermined"


def test_title_term_and_faction_forms_resolve():
    ix1 = Index(json.loads((ROOT / "worldbible" / "worldbible_v1.json").read_text()))
    for form, eid in [("고원 수호자 오스카르 브란", "oskar"), ("등불지기 토발드", "tovald"),
                      ("소금 길드의 벤토 사르", "bento"), ("잿가지 기사단 하렌드 발크", "harend")]:
        assert ix1.resolve(form)["id"] == eid


def test_unrelated_name_error_does_not_drop_kept():
    qs = good_quests()
    qs[4]["steps"].append(S("이동", None, "서리 관문 성채"))  # 함정과 상관없는 단계의 이름 오류
    assert status(qs)[5] == "kept"
    qs[4]["steps"][0] = S("받기", "미르나 님", "린도르", "다르고의 가면")  # 함정 사물을 다루는 단계의 이름 오류
    assert status(qs)[5] == "undetermined"


def test_missing_earlier_quest_breaks_premise():
    qs = [q for q in good_quests() if q["no"] != 3]  # 가면을 미르나에게 맡기는 3번이 빠짐
    qs[-1]["steps"][0] = S("받기", "베일", "잿돌 요새", "다르고의 가면")
    assert status(qs)[5] == "undetermined"
    qs = [q for q in good_quests() if q["no"] != 2]  # 베일을 쓰러뜨리는 2번이 빠짐
    qs[2]["steps"] = [S("대화", "베일", "잿돌 요새")]
    assert status(qs)[4] == "undetermined"


def test_dead_npc_in_investigate_slot_is_not_death_probe_error():
    qs = good_quests()
    qs[3]["steps"] = [S("조사", "베일", "잿돌 요새"), S("대화", "하렌드 발크", "서리 관문")]
    v = check_line(LINE, qs, IX)
    assert [x["rule"] for x in v] == ["R2"]  # 완수 판정에는 걸린다
    assert status(qs)[4] == "undetermined"  # 묻지는 않았으니 함정 오류는 아니다


def test_place_and_suffix_name_forms_resolve():
    for form, eid in [("서리 관문의 하렌드 발크", "harend"), ("달빛 나루의 하렌", "haren"), ("툰가르 장로", "tungar"),
                      ("세드릭 몰 재상", "cedric")]:
        assert IX.resolve(form)["id"] == eid


def test_quest_number_as_string():
    qs = good_quests()
    for q in qs:
        q["no"] = str(q["no"])
    assert check_line(LINE, qs, IX) == []


def test_score_counts_error_types_only_for_error_status():
    qs = good_quests()
    qs[2]["steps"] = [S("이동", None, "린도르")]  # 3번 목표 실패
    qs[4]["steps"][0] = S("받기", "미르나", "린도르", "다르고의 가면")  # 그 결과 5번 R4
    cell = {"line_id": "T01", "model": "m", "condition": "C1", "rep": 1,
            "attempts": [{"quests": qs, "violations": check_line(LINE, qs, IX), "meta": {}}]}
    row = score_cell(LINE, cell, IX)
    assert row["final_probes"]["5"]["status"] == "undetermined"
    assert row["final_state_error_types"] == {} and row["final_probes"]["5"]["rules"] == []


def test_non_string_fields_do_not_crash():
    for bad in ({"npc": ["미르나"]}, {"place": 3}, {"item": True}, {"action": 1}):
        qs = good_quests()
        qs[4]["steps"][0].update(bad)
        v = check_line(LINE, qs, IX)
        assert any(x["rule"] == "R0" for x in v)
    qs = good_quests()
    qs[0]["giver"] = "세드릭 몰"
    assert any(x["rule"] == "R0" for x in check_line(LINE, qs, IX))


def test_brief_style_name_forms_resolve():
    ix1 = Index(json.loads((ROOT / "worldbible" / "worldbible_v1.json").read_text()))
    for form, eid in [("린도르의 재상 세드릭 몰", "cedric"), ("붉은 시장의 미르네", "mirne"),
                      ("붉은 시장의 여관 주인 미르네", "mirne"), ("달빛 나루의 약초상 마브", "mab"),
                      ("린도르의 토발드", "tovald")]:
        assert ix1.resolve(form)["id"] == eid, form


def test_unreadable_field_symmetry():
    qs = good_quests()
    qs[4]["steps"][1]["place"] = "테살 항 길드 회관"  # 건네는 단계의 장소 - 판정에 쓰이지 않는다
    assert status(qs)[5] == "kept"
    qs = good_quests()
    qs[4]["steps"][0]["item"] = "가면"  # 얻는 단계의 사물을 못 알아봄 - 뒤 전달의 R6 은 판정 불가
    assert status(qs)[5] == "undetermined"
    qs = good_quests()
    qs[4]["steps"][0]["action"] = "되찾기"
    assert status(qs)[5] == "undetermined"


def test_quest_number_with_suffix():
    qs = good_quests()
    for q in qs:
        q["no"] = f"{q['no']}번"
    assert check_line(LINE, qs, IX) == []


def test_custody_probe_without_handling_item_is_undetermined():
    qs = good_quests()
    qs[4]["steps"] = [S("대화", "벤토 사르", "테살 항")]  # 가면을 다루지 않음 - R7 만
    assert status(qs)[5] == "undetermined"


def test_earlier_goal_miss_is_not_counted_again_at_probe():
    qs = good_quests()
    qs[2]["steps"] = [S("이동", None, "린도르")]  # 3번에서 가면을 미르나에게 맡기지 않음 - R7
    qs[4]["steps"][0] = S("받기", "미르나", "린도르", "다르고의 가면")  # 개요대로 미르나에게서 받으면 R4
    assert status(qs)[5] == "undetermined"


def test_title_name_forms_resolve():
    for form, eid in [("선장 로자 마렌", "rosa"), ("약초상 마브", "mab"), ("실피 장로 라에넬", "laenel"),
                      ("드바르 장로 툰가르", "tungar"), ("기사단장 하렌드 발크", "harend"), ("상단주 벤토 사르", "bento")]:
        assert IX.resolve(form)["id"] == eid
    qs = good_quests()
    qs[3]["steps"] = [S("대화", "반란 잔당 우두머리 베일", "잿돌 요새")]  # 죽은 베일을 직함으로 불러도 R2
    assert only(check_line(LINE, qs, IX))["rule"] == "R2"


def test_unresolved_npc_is_not_double_counted():
    qs = good_quests()
    qs[4]["steps"][0] = S("받기", "미르나 님", "린도르", "다르고의 가면")  # 이름을 못 알아봄 - R1 만
    assert [x["rule"] for x in check_line(LINE, qs, IX)] == ["R1"]


def test_faction_item_with_storage_only_given_there():
    qs = good_quests()
    qs[3]["steps"] = [S("받기", "토발드", "등불 대성소", "새벽의 종")]  # 교단 수장이지만 종은 수도원에 있다
    assert only(check_line(LINE, qs, IX))["rule"] == "R4"
    qs[3]["steps"] = [S("받기", "이렌", "하얀 절벽 수도원", "새벽의 종")]
    assert check_line(LINE, qs, IX) == []


def test_return_item_given_in_quest():
    line = {"id": "T02", "giver": "하렌드 발크", "probes": {},
            "quests": [{"brief": "검을 하렌에게 맡기고 수리된 검을 돌려받아 하렌드에게 가져간다.",
                        "goals": [{"hold": ["dawn_sword", "harend"]}]}]}
    qs = [Q(1, [S("받기", "하렌드 발크", "서리 관문", "새벽의 검"), S("전달", "하렌", "달빛 나루", "새벽의 검"),
                S("받기", "하렌", "달빛 나루", "새벽의 검"), S("전달", "하렌드 발크", "서리 관문", "새벽의 검")],
            giver=("하렌드 발크", "서리 관문"))]
    assert check_line(line, qs, IX) == []


# 사건 시점 - 개요가 이미 일어난 일로 알리면 start, 퀘스트 안 사건이면 end
RING = {"id": "T03", "giver": "벤토 사르", "probes": {2: "custody"},
        "quests": [{"brief": "반지를 미르네가 보관 중이라는 소문을 확인한다.", "goals": []},
                   {"brief": "미르네가 반지를 로자에게 맡겼다고 알려 준다. 반지를 벤토에게 돌려준다.",
                    "goals": [{"hold": ["salt_ring", "bento"]}]}],
        "events": [{"quest": 1, "at": "end", "hold": ["salt_ring", "mirne"]},
                   {"quest": 2, "at": "start", "hold": ["salt_ring", "rosa"]}]}


def ring_quests(source):
    return [Q(1, [S("대화", "미르네", "붉은 시장")], giver=("벤토 사르", "테살 항")),
            Q(2, [S("받기", source, "테살 항", "소금 인장 반지"), S("전달", "벤토 사르", "테살 항", "소금 인장 반지")],
              giver=("벤토 사르", "테살 항"))]


def test_event_at_start():
    assert check_line(RING, ring_quests("로자 마렌"), IX) == []
    x = only(check_line(RING, ring_quests("미르네"), IX))
    assert (x["rule"], x["kind"]) == ("R4", "state")


def test_goals_checked_before_end_events():
    line = copy.deepcopy(LINE)
    line["events"] = [{"quest": 2, "at": "end", "hold": ["dargo_mask", "player"]}]
    qs = good_quests()
    qs[1]["steps"] = [S("처치", "베일", "잿돌 요새")]  # 가면을 거두지 않음 - 끝 사건이 대신 채워 주면 안 된다
    x = only(check_line(line, qs, IX))
    assert (x["rule"], x["quest"]) == ("R7", 2)


# ---- 라인 형식 ---------------------------------------------------------------

def test_validate_lines():
    assert validate_lines([LINE, RING], IX) == []
    assert validate_lines([LINE], IX, probes_per_line={"custody": 1, "death": 1}) == []
    bad = copy.deepcopy(LINE)
    bad["probes"] = {9: "custody", 4: "boss"}
    bad["events"] = [{"quest": 1, "at": "middle", "hold": ["nope", "player"]}]
    errs = validate_lines([bad], IX, probes_per_line={"custody": 2, "death": 1})
    assert any("범위 밖" in e for e in errs) and any("boss" in e for e in errs)
    assert any("at 은" in e for e in errs) and any("사물 id" in e for e in errs)
    assert any("custody 함정이 1 개" in e for e in errs)


# ---- 설정집 v1 과 라인 풀 (실험 상세 설계 1-1, 1-2) ---------------------------------

WB1 = json.loads((ROOT / "worldbible" / "worldbible_v1.json").read_text())
IX1 = Index(WB1)
POOLS = {"v1": ROOT / "scenarios" / "questlines_v1.yaml", "pre": ROOT / "scenarios" / "questlines_pre.yaml"}


def test_worldbible_v1_state_attributes_match_v0_tables():
    from worldbible.validate import check_integrity

    assert check_integrity(WB1) == []
    assert IX1.access == V0_ACCESS and IX1.inside == V0_PLACE_INSIDE
    assert IX1.copy_at == {k: set(v) for k, v in V0_COPY_AT.items()}
    objects = [e for e in WB1["entities"] if e["type"] == "object"]
    assert len(objects) == 22
    v0_ids = {e["id"] for e in WB["entities"]}
    for e in WB["entities"]:  # v0 엔티티의 이름, 설명은 그대로
        e1 = IX1.ent[e["id"]]
        assert (e1["name"], e1["description"], e1.get("aliases")) == (e["name"], e["description"], e.get("aliases"))
    assert WB1["constraints"] == WB["constraints"] and WB1["relations"][:len(WB["relations"])] == WB["relations"]
    assert all(e["id"] in v0_ids or e["type"] == "object" for e in WB1["entities"])


def test_good_line_passes_on_v1():
    assert check_line(LINE, good_quests(), IX1) == []


@pytest.mark.parametrize("pool", sorted(POOLS))
def test_line_pool_passes_audit(pool):
    lines = load_lines(POOLS[pool])
    assert len(lines) == {"v1": 40, "pre": 6}[pool]
    assert validate_lines(lines, IX1, probes_per_line=PROBE_MIX) == []
    for line in lines:
        assert audit_line(line, IX1) == [], line["id"]


@pytest.mark.parametrize("pool", sorted(POOLS))
def test_probe_distances_resolve_every_probe(pool):
    from questline.lines import probe_distances

    for line in load_lines(POOLS[pool]):
        d = probe_distances(line, IX1)
        assert set(d) == set(line["probes"]), line["id"]
        assert all(v is not None and 0 <= v <= 4 for v in d.values()), (line["id"], d)


def test_probe_distances_counts_from_state_change():
    from questline.lines import probe_distances

    line = next(l for l in load_lines(POOLS["v1"]) if l["id"] == "M40")
    assert line["events"] == [{"quest": 2, "at": "end", "dead": "tovald"}]
    assert probe_distances(line, IX1)[3] == 1  # 2번 퀘스트 끝에 죽고 3번 퀘스트에서 묻는다


def test_line_pools_do_not_share_ids_or_reuse_pilot_lines():
    ids = [l["id"] for p in POOLS.values() for l in load_lines(p)]
    assert len(ids) == len(set(ids))
    assert not any(i.startswith("L") for i in ids)


def test_audit_catches_broken_solution_and_fake_probes():
    m = copy.deepcopy(next(l for l in load_lines(POOLS["v1"]) if l["id"] == "M01"))
    bad = copy.deepcopy(m)
    bad["solution"][3]["steps"] = [["전달", "세드릭 몰", "린도르", "재상의 인장"]]  # 되찾기 단계 누락
    assert any("R6" in e for e in audit_line(bad, IX1))
    bad = copy.deepcopy(m)
    bad["probes"] = {2: "custody", 3: "custody", 4: "death"}  # 2번은 옮겨진 사물을 다루지 않는다
    assert any("소유 함정인데" in e for e in audit_line(bad, IX1))
    bad = copy.deepcopy(m)
    bad["probes"] = {1: "death", 3: "custody", 5: "custody"}  # 죽음보다 앞
    assert any("죽음 함정인데" in e for e in audit_line(bad, IX1))
    bad = copy.deepcopy(m)
    bad["quests"][3]["brief"] = "재상의 인장을 다시 세드릭 몰에게 가져간다."
    assert any("'다시'" in e for e in audit_line(bad, IX1))


def test_audit_catches_death_answerer_named_in_line():
    m = next(l for l in load_lines(POOLS["v1"]) if l["id"] == "M01")
    assert m["probes"][5] == "death" and m["death_answerers"] == ["bento"]
    for brief in ("상단주 벤토에게 소식을 전한다.", "벤토 사르에게 소식을 전한다.", "벤토에게 소식을 전한다."):  # 별칭, 이름, 성 뺀 이름
        bad = copy.deepcopy(m)
        bad["quests"][1]["brief"] = brief
        assert any("M01-2: 죽음 함정 대답자" in e for e in audit_line(bad, IX1)), brief
    bad = copy.deepcopy(m)
    del bad["death_answerers"]
    assert any("death_answerers 가 없다" in e for e in audit_line(bad, IX1))
    bad = copy.deepcopy(m)
    bad["death_answerers"] = ["mirne"]  # 모범 풀이는 벤토를 찾아간다
    assert any("누구도 아니다" in e for e in audit_line(bad, IX1))
    bad = copy.deepcopy(m)
    bad["death_answerers"] = ["mabb"]
    assert any("death_answerers 의 'mabb'" in e for e in validate_lines([bad], IX1))


def test_pool_traps_are_caught_by_checker():
    m = next(l for l in load_lines(POOLS["v1"]) if l["id"] == "M01")
    qs = solution_quests(m)
    qs[3]["steps"][0] = S("받기", "세드릭 몰", "린도르", "재상의 인장")  # 옛 주인에게서 받는다
    qs[4]["steps"] = [S("대화", "로자 마렌", "테살 항")]  # 죽은 선장에게 묻는다
    v = check_line(m, qs, IX1)
    assert [(x["rule"], x["kind"], x["quest"]) for x in v] == [("R4", "state", 4), ("R2", "state", 5)]
    assert {k: bool(e) for k, e in probe_errors(m, v).items()} == {3: False, 4: True, 5: True}


def test_prompt_hides_solution_and_goals():
    m = next(l for l in load_lines(POOLS["v1"]) if l["id"] == "M01")
    user = build_messages(WB1, m)[-1]["content"]
    assert m["quests"][2]["brief"] in user
    assert "solution" not in user and "chancellor_seal" not in user and "[받기," not in user
    assert "death_answerers" not in user


def test_parse_probe_mix():
    assert parse_probe_mix("custody=2,death=1") == PROBE_MIX
    assert parse_probe_mix("none") is None
    with pytest.raises(ValueError):
        parse_probe_mix("boss=1")


# ---- 조건 실행 ---------------------------------------------------------------

class FakeClient:
    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.calls = []

    def chat(self, spec, messages, sampling, fetch_generation=True):
        self.calls.append({"messages": copy.deepcopy(messages), "seed": sampling["seed"]})
        text = self.outputs.pop(0)
        return SimpleNamespace(text=text, meta={"usage": {"cost_usd": 0.01}, "latency_ms": 1000, "finish_reason": "stop"})


GOOD = json.dumps({"quests": good_quests()}, ensure_ascii=False)
BAD_Q = good_quests()
BAD_Q[4]["steps"] = [S("전달", "벤토 사르", "테살 항", "다르고의 가면")]
BAD = json.dumps({"quests": BAD_Q}, ensure_ascii=False)
SPEC = SimpleNamespace(name="fake")
SAMPLING = {"temperature": 0.7, "top_p": 0.9, "max_tokens": 4000, "seed": 42}


def test_c1_single_attempt():
    c = FakeClient([BAD])
    cell = run_cell(c, SPEC, WB, IX, LINE, "C1", 1, SAMPLING)
    assert len(cell["attempts"]) == 1 and c.calls[0]["seed"] == 42


def test_c2_feedback_then_pass():
    c = FakeClient([BAD, GOOD])
    cell = run_cell(c, SPEC, WB, IX, LINE, "C2", 2, SAMPLING)
    assert [a["seed"] for a in cell["attempts"]] == [142, 143]
    second = c.calls[1]["messages"]
    assert second[-2] == {"role": "assistant", "content": BAD}
    assert "5번 퀘스트 1단계" in second[-1]["content"] and "미르나" in second[-1]["content"]
    assert cell["attempts"][-1]["violations"] == []


def test_c3_resends_first_request():
    c = FakeClient([BAD, BAD, GOOD])
    cell = run_cell(c, SPEC, WB, IX, LINE, "C3", 1, SAMPLING)
    assert [a["seed"] for a in cell["attempts"]] == [42, 43, 44]
    assert c.calls[1]["messages"] == c.calls[0]["messages"] == c.calls[2]["messages"]


def test_c4_selfcheck_has_no_violation_list():
    # C4 는 C2 와 대화 구조, seed 가 같고 위반 목록만 없다
    c2, c4 = FakeClient([BAD, GOOD]), FakeClient([BAD, GOOD])
    run_cell(c2, SPEC, WB, IX, LINE, "C2", 2, SAMPLING)
    cell = run_cell(c4, SPEC, WB, IX, LINE, "C4", 2, SAMPLING)
    assert [a["seed"] for a in cell["attempts"]] == [142, 143] and cell["condition"] == "C4"
    m2, m4 = c2.calls[1]["messages"], c4.calls[1]["messages"]
    assert m4[:-1] == m2[:-1] and m4[-2] == {"role": "assistant", "content": BAD}
    assert "5번 퀘스트" not in m4[-1]["content"] and "미르나" not in m4[-1]["content"]
    assert m4[-1]["content"].splitlines()[-1] == m2[-1]["content"].splitlines()[-1]
    assert m4[-1]["content"].startswith(m2[-1]["content"].split(" 검사기가")[0])
    c = FakeClient([BAD] * 5)
    assert len(run_cell(c, SPEC, WB, IX, LINE, "C4", 1, SAMPLING, max_regen=2)["attempts"]) == 3
    from questline.run import CONDITIONS
    assert CONDITIONS == ("C1", "C2", "C3")  # 배치 기본 조건과 고정 분석의 조건은 그대로다


def test_max_regen_cap():
    c = FakeClient([BAD] * 5)
    cell = run_cell(c, SPEC, WB, IX, LINE, "C2", 1, SAMPLING, max_regen=2)
    assert len(cell["attempts"]) == 3


def test_parse_failure_is_r0():
    c = FakeClient(["죄송합니다"])
    cell = run_cell(c, SPEC, WB, IX, LINE, "C1", 1, SAMPLING)
    assert cell["attempts"][0]["violations"][0]["rule"] == "R0"


def test_parse_reads_first_object_and_keeps_trailing_text():
    # 올바른 JSON 뒤에 설명과 두 번째 객체가 붙은 출력(예비 측정 gpt) - 첫 객체를 읽고 붙은 문자열을 돌려준다
    tail = '(End of response)"}]} 다시 출력한다 {"quests": []}'
    assert parse_quests(GOOD + "\n" + tail) == json.loads(GOOD)["quests"]
    assert split_json(GOOD + "\n" + tail)[1] == tail
    assert split_json("```json\n" + GOOD + "\n```")[1] == ""
    assert parse_quests(GOOD[: len(GOOD) // 2]) is None  # 잘린 출력은 여전히 못 읽는다
    # 최대 길이에서 잘린 출력은 앞에 온전한 객체가 있어도 형식 실패(R0)로 둔다
    q, v = judge(LINE, GOOD + "\n{\"quests\": [", IX, "length")
    assert q is None and v[0]["rule"] == "R0" and v[0]["msg"] == "JSON 을 읽지 못했다"
    assert judge(LINE, GOOD + "\n{\"quests\": [", IX, "stop")[0] == json.loads(GOOD)["quests"]


def test_prompt_contains_briefs_not_goals():
    msgs = build_messages(WB, LINE)
    user = msgs[-1]["content"]
    assert "5. 다르고의 가면을 벤토 사르에게 넘긴다." in user
    assert "goals" not in user and "dargo_mask" not in user
    assert parse_quests("```json\n" + GOOD + "\n```") == json.loads(GOOD)["quests"]


def test_score_cell():
    c = FakeClient([BAD, GOOD])
    cell = run_cell(c, SPEC, WB, IX, LINE, "C2", 1, SAMPLING)
    row = score_cell(LINE, cell, IX)
    assert row["final_completable"] is True and row["first_completable"] is False
    assert row["first_probes"]["5"] == {"type": "custody", "status": "error", "error": True, "rules": ["R6"]}
    assert row["final_probes"]["4"]["status"] == "kept"  # 4번 죽음 함정에서 하렌드 발크를 만났다
    assert row["first_state_error_types"] == {"missing_acquire": 1}
    assert row["regenerations"] == 1 and row["cost_usd"] == pytest.approx(0.02) and row["latency_s"] == 2.0


def test_suite_runs_on_both_worldbibles(worldbible):
    assert IX is SUITE_IX[worldbible]  # 판을 나눈 시험은 그 판의 설정집으로 돈다
    assert ("다르고의 가면" in IX.ent["dargo_mask"]["name"]) and (len([e for e in IX.ent.values() if e["type"] == "object"])
                                                                  == {"v0": 8, "v1": 22}[worldbible])


def test_unparsed_output_makes_all_probes_undetermined():
    from questline.run import judge
    quests, viol = judge(LINE, "이건 JSON 이 아니다", IX)
    assert quests is None and viol[0]["quest"] is None
    from questline.checker import probe_status
    assert probe_status(LINE, quests, viol, IX) == {4: "undetermined", 5: "undetermined"}
    cell = {"line_id": "T01", "model": "m", "condition": "C1", "rep": 1,
            "attempts": [{"quests": quests, "violations": viol, "meta": {}}]}
    row = score_cell(LINE, cell, IX)
    assert row["final_parsed"] is False and row["final_completable"] is False


def test_outer_inner_place_form_resolves():
    for form, eid in [("테살 항 붉은 시장", "red_market"), ("테살 항의 붉은 시장", "red_market"), ("린도르 등불 대성소", "lantern_sanctum")]:
        assert IX.resolve(form)["id"] == eid
    qs = good_quests()
    qs[3]["steps"] = [S("대화", "미르네", "테살 항 붉은 시장")]
    assert check_line(LINE, qs, IX) == []


def test_score_counts_goals_met_with_missing_quest_and_unparsed():
    qs = good_quests()
    row = score_cell(LINE, {"line_id": "T01", "model": "m", "condition": "C1", "rep": 1,
                            "attempts": [{"quests": qs, "violations": check_line(LINE, qs, IX), "meta": {}}]}, IX)
    assert (row["final_goals_total"], row["final_goals_met"]) == (5, 5)
    qs = [q for q in good_quests() if q["no"] != 3]  # 3번(목표 1개)이 빠짐
    row = score_cell(LINE, {"line_id": "T01", "model": "m", "condition": "C1", "rep": 1,
                            "attempts": [{"quests": qs, "violations": check_line(LINE, qs, IX), "meta": {}}]}, IX)
    assert row["final_goals_met"] < 5 and row["final_goals_met"] <= 4
    from questline.run import judge
    quests, viol = judge(LINE, "JSON 아님", IX)
    row = score_cell(LINE, {"line_id": "T01", "model": "m", "condition": "C1", "rep": 1,
                            "attempts": [{"quests": quests, "violations": viol, "meta": {}}]}, IX)
    assert (row["final_goals_total"], row["final_goals_met"]) == (5, 0)
