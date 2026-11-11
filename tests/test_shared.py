"""오프라인 테스트 - 두 주제가 함께 쓰는 부분: 호출 어댑터, 설정 동결값, 닫힌 세계 지시, 설정집 검증기, seed 규칙.

    .venv/bin/python -m pytest -q

네트워크 호출은 전부 _request 또는 urlopen 을 목킹한다. 이전 주제(세계관 일관성)의 테스트에서 공통 부분을 옮겼다 -
나머지는 태그 lore-consistency-final 의 tests/test_pipeline.py 에 있다.
"""

from __future__ import annotations

import copy
import email.message
import json
import urllib.error
from pathlib import Path

import pytest

import pipeline.generators as g
from pipeline.generators import (
    AdapterError,
    ModelSpec,
    OpenRouterClient,
    SnapshotMismatch,
    load_config,
    version_of,
)
from pipeline.prompting import CLOSED_WORLD_INSTRUCTION, render_worldbible
from questline.prompting import build_messages as build_line_messages
from questline.run import seed_for

ROOT = Path(__file__).resolve().parent.parent
WB = json.loads((ROOT / "worldbible" / "mini_worldbible.json").read_text(encoding="utf-8"))
FAKE_KEY = "test-key-not-a-real-key"
SAMPLING = {"temperature": 0.7, "top_p": 0.9, "max_tokens": 512, "seed": 42}

@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(g.time, "sleep", lambda s: None)


def ok_response(content="이센이 은빛탑에서 기다린다.", reasoning_tokens=0, provider="OpenAI", model="openai/gpt-5.2"):
    return {
        "id": "gen-1",
        "model": model,
        "provider": provider,
        "choices": [{"message": {"content": content}, "finish_reason": "stop"}],
        "usage": {
            "prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15, "cost": 0.001,
            "completion_tokens_details": {"reasoning_tokens": reasoning_tokens},
        },
    }


def client(responses=None, **kw):
    """_request 를 큐로 대체한 클라이언트. responses 는 (payload | Exception) 목록."""
    c = OpenRouterClient(api_key=FAKE_KEY, **kw)
    if responses is not None:
        queue = list(responses)

        def fake_request(method, path, body=None):
            item = queue.pop(0)
            if isinstance(item, Exception):
                raise item
            return item, {"attempts": 1, "last_attempt_ms": 100}

        c._request = fake_request  # type: ignore[method-assign]
    return c


class _FakeHTTPError(urllib.error.HTTPError):
    def __init__(self, code, body=b"{}", headers=None):
        h = email.message.Message()
        for k, v in (headers or {}).items():
            h[k] = v
        super().__init__("http://x", code, "err", h, None)
        self._body = body

    def read(self):
        return self._body


# ---- 어댑터: 본문 -------------------------------------------------------------

def test_build_body_pins_provider_and_freezes_sampling():
    c = client(allow_fallbacks=False)
    spec = ModelSpec(name="gpt", router_slug="openai/x", provider_tag="openai", snapshot="2026-01-01")
    body = c.build_body(spec, [{"role": "user", "content": "hi"}], SAMPLING)
    assert body["provider"] == {"allow_fallbacks": False, "order": ["openai"]}
    assert body["seed"] == 42 and body["temperature"] == 0.7 and body["top_p"] == 0.9 and body["max_tokens"] == 512


def test_build_body_without_tag_has_no_order():
    spec = ModelSpec(name="smoke", router_slug="google/g:free", provider_tag=None)
    assert "order" not in client().build_body(spec, [], {"seed": 42})["provider"]


def test_request_extra_merges_but_cannot_override_frozen_fields():
    c = client()
    spec = ModelSpec(name="smoke", router_slug="a/b", request_extra={"reasoning": {"enabled": False}})
    assert c.build_body(spec, [], {"seed": 42})["reasoning"] == {"enabled": False}
    bad = ModelSpec(name="smoke", router_slug="a/b", request_extra={"seed": 7})
    with pytest.raises(AdapterError, match="동결 필드"):
        c.build_body(bad, [], {"seed": 42})


def test_model_spec_rejects_tbd_and_missing():
    with pytest.raises(AdapterError, match="TBD"):
        ModelSpec.from_config("gpt", {"models": {"gpt": {"router_slug": "TBD"}}})
    with pytest.raises(AdapterError, match="없다"):
        ModelSpec.from_config("gpt", {})


def test_model_spec_deep_copies_request_extra():
    cfg = {"models": {"x": {"router_slug": "a/b", "request_extra": {"reasoning": {"enabled": False}}}}}
    spec = ModelSpec.from_config("x", cfg)
    spec.request_extra["reasoning"]["enabled"] = True
    assert cfg["models"]["x"]["request_extra"]["reasoning"]["enabled"] is False


# ---- 어댑터: chat() 과 건별 대조 ----------------------------------------------

def test_chat_records_meta_and_passes_verification():
    gen_lookup = {"data": {"model": "openai/gpt-5.2-20251211", "provider_name": "OpenAI", "total_cost": 0.002}}
    c = client(responses=[ok_response(), gen_lookup])
    spec = ModelSpec(name="gpt", router_slug="openai/gpt-5.2", provider_tag="openai", snapshot="gpt-5.2-20251211")
    out = c.chat(spec, [{"role": "user", "content": "x"}], SAMPLING)
    m = out.meta
    assert out.text.startswith("이센")
    assert m["latency_ms"] == 100 and m["attempts"] == 1
    assert m["request_utc"].endswith("+00:00") and m["response_utc"] >= m["request_utc"]
    assert m["sampling"]["seed"] == 42 and m["snapshot_frozen"] == "gpt-5.2-20251211"
    assert m["usage"]["reasoning_tokens"] == 0 and m["generation"]["model_dated"] == "openai/gpt-5.2-20251211"
    assert m["warnings"] == []


def test_request_retries_connection_reset_while_reading(monkeypatch):
    calls = {"n": 0}

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self, *a):
            return b'{"ok": 1}'

    def fake_urlopen(req, timeout=None):
        calls["n"] += 1
        if calls["n"] == 1:
            raise ConnectionResetError(54, "Connection reset by peer")
        return _Resp()

    monkeypatch.setattr(g.urllib.request, "urlopen", fake_urlopen)
    payload, stats = OpenRouterClient(api_key=FAKE_KEY)._request("GET", "/x")
    assert payload == {"ok": 1} and stats["attempts"] == 2


def test_chat_records_cache_tokens_when_given():
    resp = ok_response()
    resp["usage"]["prompt_tokens_details"] = {"cached_tokens": 8, "cache_write_tokens": 0}
    gen_lookup = {"data": {"model": "openai/gpt-5.2-20251211", "native_tokens_cached": 8, "cache_discount": 0.0007}}
    spec = ModelSpec(name="gpt", router_slug="openai/gpt-5.2")
    m = client(responses=[resp, gen_lookup]).chat(spec, [], SAMPLING).meta
    assert m["usage"]["cached_tokens"] == 8 and m["usage"]["cache_write_tokens"] == 0
    assert m["generation"]["native_tokens_cached"] == 8 and m["generation"]["cache_discount"] == 0.0007
    m = client(responses=[ok_response()]).chat(spec, [], SAMPLING, fetch_generation=False).meta
    assert m["usage"]["cached_tokens"] is None  # 주지 않는 공급사


def test_chat_rejects_missing_choices_and_empty_content():
    spec = ModelSpec(name="gpt", router_slug="openai/gpt-5.2")
    with pytest.raises(AdapterError, match="choices"):
        client(responses=[{"error": {"message": "x"}}]).chat(spec, [], SAMPLING, fetch_generation=False)
    with pytest.raises(AdapterError, match="비었다"):
        client(responses=[ok_response(content="  ")]).chat(spec, [], SAMPLING, fetch_generation=False)


def test_chat_strict_rejects_reasoning_tokens_and_wrong_provider():
    spec = ModelSpec(name="gpt", router_slug="openai/gpt-5.2", provider_tag="openai")
    with pytest.raises(AdapterError, match="reasoning_tokens=598"):
        client(responses=[ok_response(reasoning_tokens=598)]).chat(spec, [], SAMPLING, fetch_generation=False)
    with pytest.raises(AdapterError, match="공급 경로 불일치"):
        client(responses=[ok_response(provider="Azure")]).chat(spec, [], SAMPLING, fetch_generation=False)
    # strict=False 면 경고로만 남긴다
    out = client(responses=[ok_response(provider="Azure")], strict=False).chat(spec, [], SAMPLING, fetch_generation=False)
    assert any("공급 경로" in w for w in out.meta["warnings"])


def test_chat_accepts_provider_display_names():
    """'google-ai-studio' 요청에 'Google AI Studio' 응답, 'anthropic' 에 'Anthropic'."""
    for tag, shown in (("google-ai-studio", "Google AI Studio"), ("anthropic", "Anthropic"), ("openai", "OpenAI")):
        spec = ModelSpec(name="m", router_slug="a/b", provider_tag=tag)
        out = client(responses=[ok_response(provider=shown)]).chat(spec, [], SAMPLING, fetch_generation=False)
        assert out.meta["warnings"] == [], tag


def test_chat_strict_rejects_snapshot_drift_from_generation_lookup():
    spec = ModelSpec(name="gpt", router_slug="openai/gpt-5.2", provider_tag="openai", snapshot="gpt-5.2-20251211")
    drifted = {"data": {"model": "openai/gpt-5.2-20260301", "provider_name": "OpenAI"}}
    with pytest.raises(SnapshotMismatch, match="20260301"):
        client(responses=[ok_response(), drifted]).chat(spec, [], SAMPLING)


def test_chat_warns_when_generation_lookup_fails():
    spec = ModelSpec(name="gpt", router_slug="openai/gpt-5.2", provider_tag="openai", snapshot="gpt-5.2-20251211")
    out = client(responses=[ok_response(), *([AdapterError("404")] * 3)]).chat(spec, [], SAMPLING)
    assert out.meta["generation"] is None
    assert any("generation 조회 실패" in w for w in out.meta["warnings"])
    assert out.meta["usage"]["cost_usd"] == 0.001  # generation 없으면 usage.cost 가 비용 기록이다


# ---- 어댑터: 재시도 ------------------------------------------------------------

def test_request_retries_on_429_then_succeeds(monkeypatch):
    sleeps: list[float] = []
    monkeypatch.setattr(g.time, "sleep", lambda s: sleeps.append(s))
    responses = [_FakeHTTPError(429, headers={"Retry-After": "3"}), _FakeHTTPError(503), None]

    class FakeResp:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return b'{"ok": true}'

    def fake_urlopen(req, timeout):
        item = responses.pop(0)
        if item is not None:
            raise item
        return FakeResp()

    monkeypatch.setattr(g.urllib.request, "urlopen", fake_urlopen)
    payload, stats = OpenRouterClient(api_key=FAKE_KEY)._request("GET", "/x")
    assert payload == {"ok": True} and stats["attempts"] == 3
    assert sleeps == [3.0, 4.0]  # Retry-After 를 따르고, 그다음은 백오프 2*2^1


def test_request_fails_fast_on_400_and_exhausts_on_429(monkeypatch):
    def raise_(err):
        def _f(req, timeout):
            raise err
        return _f

    monkeypatch.setattr(g.urllib.request, "urlopen", raise_(_FakeHTTPError(400, b'{"error":"bad"}')))
    with pytest.raises(AdapterError, match="HTTP 400"):
        OpenRouterClient(api_key=FAKE_KEY)._request("GET", "/x")
    monkeypatch.setattr(g.urllib.request, "urlopen", raise_(_FakeHTTPError(429)))
    with pytest.raises(AdapterError, match="HTTP 429"):
        OpenRouterClient(api_key=FAKE_KEY, max_retries=2)._request("GET", "/x")


# ---- 어댑터: snapshot 대조 -----------------------------------------------------

def test_version_of_parses_endpoint_names_and_model_ids():
    assert version_of("OpenAI | openai/gpt-5.2-20251211") == "gpt-5.2-20251211"
    assert version_of("google/gemma-4-31b-it-20260402:free") == "gemma-4-31b-it-20260402"
    assert version_of("Google AI Studio | google/gemini-2.5-flash-lite") == "gemini-2.5-flash-lite"
    assert version_of("garbage") is None


def test_snapshot_check_exact_match_tag_filter_and_errors(monkeypatch):
    c = client()
    fake = {"endpoints": [
        {"name": "OpenAI | openai/gpt-x-20260101", "tag": "openai"},
        {"name": "OpenAI | openai/gpt-x-20260101", "tag": "openai/flex"},
        {"name": "Azure | openai/gpt-x-20251201", "tag": "azure"},
    ]}
    monkeypatch.setattr(c, "get_endpoints", lambda slug: fake)

    def spec(snapshot, tag="openai"):
        return ModelSpec(name="gpt", router_slug="openai/gpt-x", provider_tag=tag, snapshot=snapshot)

    r = c.check_snapshot(spec("gpt-x-20260101"))
    assert r["observed_versions"] == ["gpt-x-20260101"] and not r["skipped"]  # azure 판은 tag 로 걸러진다
    with pytest.raises(SnapshotMismatch, match="동결"):
        c.check_snapshot(spec("gpt-x-20250101"))
    with pytest.raises(SnapshotMismatch):
        c.check_snapshot(spec("gpt-x"))  # 날짜 없는 동결값은 새 날짜 판에 통과하면 안 된다 (정확 일치)
    with pytest.raises(AdapterError, match="endpoint 가 없다"):
        c.check_snapshot(spec("gpt-x-20260101", tag="anthropic"))
    assert c.check_snapshot(spec(None))["skipped"]


# ---- 어댑터: 키 누출 -----------------------------------------------------------

def test_api_key_never_enters_records_or_errors():
    spec = ModelSpec(name="gpt", router_slug="openai/gpt-5.2", provider_tag="openai", snapshot="gpt-5.2-20251211")
    c = client(responses=[ok_response(), {"data": {"model": "openai/gpt-5.2-20251211"}}])
    out = c.chat(spec, [{"role": "user", "content": "x"}], SAMPLING)
    assert FAKE_KEY not in json.dumps(out.meta) and FAKE_KEY not in json.dumps(c.build_body(spec, [], SAMPLING))
    for bad in ({"error": {"message": "x"}}, ok_response(content="")):
        with pytest.raises(AdapterError) as ei:
            client(responses=[bad]).chat(spec, [], SAMPLING, fetch_generation=False)
        assert FAKE_KEY not in str(ei.value)


# ---- 설정 동결 (불변식 5) ------------------------------------------------------

def test_frozen_config_values():
    cfg = load_config()
    assert cfg["sampling"] == {"temperature": 0.7, "top_p": 0.9, "max_tokens": 512, "seed": 42}
    assert cfg["relay"]["allow_fallbacks"] is False
    frozen = {
        "gpt": ("openai/gpt-6-luna", "openai", "gpt-6-luna-20260922", {"reasoning": {"enabled": False}}),
        "claude": ("anthropic/claude-haiku-5.5", "anthropic", "claude-haiku-5.5-20261007", {"reasoning": {"enabled": False}}),
        "gemini": ("google/gemini-3.1-flash-lite", "google-ai-studio", "gemini-3.1-flash-lite-20260507", {"reasoning": {"enabled": False}}),
    }
    for name, (slug, tag, snap, extra) in frozen.items():
        m = cfg["models"][name]
        assert (m["router_slug"], m["provider_tag"], m["snapshot"], m["request_extra"]) == (slug, tag, snap, extra), name


def test_questline_config_values():
    q = load_config()["questline"]
    assert q == {"max_tokens": 4000, "max_regen": 2, "cost_cap_usd": 15}


# ---- 닫힌 세계 지시와 설정집 텍스트 (불변식) ------------------------------------

def test_closed_world_instruction_and_full_worldbible_in_line_request():
    line = {"id": "X", "quests": [{"brief": "의뢰를 받는다."}]}
    user = build_line_messages(WB, line)[-1]["content"]
    assert CLOSED_WORLD_INSTRUCTION in user
    assert render_worldbible(WB) in user  # 설정집 전문


def test_seed_rule():
    assert [seed_for(1, t) for t in range(3)] == [42, 43, 44]
    assert seed_for(3, 2) == 244
    with pytest.raises(ValueError):
        seed_for(0, 0)


# ---- world bible 스키마 소결정 (2026-09-07): terms 구역, faction 유형, 시간 순서 대조 ----------------

def test_whitelist_is_union_of_entity_names_and_terms_without_meta_convention():
    from worldbible.validate import check_integrity, expected_whitelist

    assert "미리엔" in expected_whitelist(WB)              # 세계명은 terms 에서 온다
    wb = copy.deepcopy(WB)
    wb["meta"]["name"] = "다른이름 연대기"                 # meta.name 첫 토큰 관례는 더 이상 화이트리스트에 영향 없음
    assert check_integrity(wb) == []
    wb["terms"] = []                                        # 용어를 빼면 목록의 '미리엔'이 잉여가 된다
    assert any("잉여" in e for e in check_integrity(wb))
    wb = copy.deepcopy(WB)
    wb["terms"].append({"term": "이센", "kind": "title", "description": "x"})
    assert any("겹침" in e for e in check_integrity(wb))   # 한 이름은 엔티티나 용어 한 곳에만


def test_terms_appear_in_worldbible_text():
    full = render_worldbible(WB)
    assert "[용어" in full and "미리엔 / world" in full
    assert "미리엔 / world" in render_worldbible(WB, {"isen"})   # 일부만 실어도 용어는 전부 싣는다


def test_before_predicate_requires_years_in_order():
    from worldbible.validate import check_integrity

    wb = copy.deepcopy(WB)
    wb["entities"].append({"id": "later", "type": "event", "name": "재건 축제", "description": "x", "attributes": {"year": 5}})
    wb["name_whitelist"].append("재건 축제")
    wb["entities"][[e["id"] for e in wb["entities"]].index("ashfire_war")]["attributes"]["year"] = 0
    wb["relations"].append({"subject": "ashfire_war", "predicate": "이전에 일어났다", "object": "later", "description": "x"})
    assert check_integrity(wb) == []
    wb["relations"][-1] = {"subject": "later", "predicate": "이전에 일어났다", "object": "ashfire_war", "description": "x"}
    assert any("시간 순서 모순" in e for e in check_integrity(wb))
    wb["entities"][-1]["attributes"] = {}
    assert any("attributes.year" in e for e in check_integrity(wb))

