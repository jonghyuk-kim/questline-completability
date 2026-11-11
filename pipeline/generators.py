"""OpenRouter 단일 어댑터 - 3사 모델을 같은 요청 형식으로 호출한다.

설계 불변식 5(README): 모든 호출에 모델 snapshot, UTC ISO8601 시각, seed,
공급자 버전 식별자를 기록한다. 모델별 공급 경로를 고정하고(provider.order +
allow_fallbacks=false), 배치 실행 전 endpoints 조회로 configs/models.yaml의
snapshot 동결값과 대조한다(다르면 실행 중단). 호출 뒤에도 응답의 실제 공급 경로,
날짜 판, 추론 토큰을 동결값과 대조한다(strict 모드에서 불일치는 오류) - endpoints
대조는 배치 전 1회뿐이라 배치 도중 판 교체를 잡으려면 건별 대조가 필요하다.

API 키는 환경 변수 OPENROUTER_API_KEY 에서만 읽고, 이 모듈이 만드는 어떤
레코드에도 넣지 않는다(tests/test_shared.py 의 test_api_key_never_enters_records_or_errors 가 meta 와 예외 문자열까지 검사).

응답 메타데이터의 출처 (2026-09-02 실측):
- chat/completions 응답: model(슬러그), provider(공급사 표시명), id(generation id),
  usage(토큰, cost, completion_tokens_details.reasoning_tokens), choices[].finish_reason.
  system_fingerprint 는 중계 응답에 실리지 않는다(null).
- GET /generation?id=: model 에 공급사 날짜 판이 붙어 온다
  (예: openai/gpt-5.2-20251211), provider_name, total_cost, native 토큰 수,
  generation_time, created_at, upstream_id. 기록이 몇 초 늦게 생긴다.
- GET /models/{author}/{slug}/endpoints: endpoints[].name 이
  "공급사 | author/슬러그-YYYYMMDD" 형식이라 snapshot 대조에 쓴다. 보장된 계약이 아니라
  파싱 실패는 오류로 처리하고 응답 원본을 결과에 남긴다.
"""

from __future__ import annotations

import http.client
import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = ROOT / "configs" / "models.yaml"
DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
ENV_KEY = "OPENROUTER_API_KEY"

# 재시도 대상: 공급사 공용 풀 한도(429), 요청 시간 초과(408), 일시 장애(5xx). 그 밖의 4xx는 즉시 실패.
RETRY_STATUS = {408, 429, 500, 502, 503, 504}


class AdapterError(RuntimeError):
    """호출 실패, 설정 오류, snapshot 불일치처럼 실행을 멈춰야 하는 오류."""


class SnapshotMismatch(AdapterError):
    """endpoints 조회 또는 응답의 날짜 판이 동결 snapshot 과 다르다 - 배치를 시작하거나 이어 가면 안 된다."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def load_config(path: Path | str = DEFAULT_CONFIG) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_api_key() -> str:
    """환경 변수에서만 읽는다. .env 는 호출 측(scripts)이 python-dotenv 로 올린다."""
    key = os.environ.get(ENV_KEY, "").strip()
    if not key:
        raise AdapterError(f"환경 변수 {ENV_KEY} 가 비어 있다 (.env 확인)")
    return key


def version_of(endpoint_or_model_name: str) -> str | None:
    """'OpenAI | openai/gpt-5.2-20251211' 또는 'openai/gpt-5.2-20251211:free' → 'gpt-5.2-20251211'."""
    tail = endpoint_or_model_name.rsplit("|", 1)[-1].strip()
    tail = tail.split(":", 1)[0]  # ':free', ':batch' 변형 접미사 제거
    if "/" not in tail:
        return None
    return tail.split("/", 1)[1] or None


@dataclass
class ModelSpec:
    """configs/models.yaml 의 models.<name> 한 항목."""

    name: str
    router_slug: str
    provider_tag: str | None = None
    snapshot: str | None = None
    provider: str | None = None
    request_extra: dict[str, Any] = field(default_factory=dict)  # 모델별 추가 요청 필드 (예: reasoning 끄기)

    @classmethod
    def from_config(cls, name: str, cfg: dict) -> "ModelSpec":
        models = cfg.get("models") or {}
        m = models.get(name)
        if m is None:
            raise AdapterError(f"configs 에 모델 '{name}' 이 없다 (있는 것: {sorted(models)})")
        slug = m.get("router_slug")
        if not slug or slug == "TBD":
            raise AdapterError(f"모델 '{name}' 의 router_slug 가 동결되지 않았다 (TBD)")
        snap = m.get("snapshot")
        return cls(
            name=name,
            router_slug=slug,
            provider_tag=m.get("provider_tag") or None,
            snapshot=None if snap in (None, "TBD") else str(snap),
            provider=m.get("provider"),
            request_extra=json.loads(json.dumps(m.get("request_extra") or {})),  # 깊은 복사
        )


@dataclass
class Generation:
    """호출 1건의 결과. text 와 meta 를 그대로 runs/ 에 남긴다."""

    text: str
    meta: dict[str, Any] = field(default_factory=dict)


class OpenRouterClient:
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 120.0,
        max_retries: int = 4,
        allow_fallbacks: bool = False,
        strict: bool = True,
    ):
        """strict: 호출 뒤 응답의 공급 경로, 날짜 판, 추론 토큰이 동결값과 다르면 오류로 멈춘다."""
        self._api_key = api_key or load_api_key()
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
        self.allow_fallbacks = allow_fallbacks
        self.strict = strict

    # ---- HTTP -------------------------------------------------------------

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/jonghyuk-kim/questline-completability",
            "X-Title": "questline-completability",
        }

    def _request(self, method: str, path: str, body: dict | None = None) -> tuple[dict, dict[str, Any]]:
        """응답 JSON 과 전송 통계(시도 횟수, 마지막 시도 지연)를 돌려준다.

        지연은 마지막(성공한) 시도만 잰다 - 재시도 대기(백오프)를 포함하면 지연 지표가
        공급사 성능이 아니라 공용 풀 혼잡을 재게 된다. 시도 횟수는 따로 남긴다.
        """
        url = f"{self.base_url}{path}"
        data = json.dumps(body).encode("utf-8") if body is not None else None
        last_err: str | None = None
        attempts = 0
        for attempt in range(self.max_retries + 1):
            attempts = attempt + 1
            req = urllib.request.Request(url, data=data, headers=self._headers(), method=method)
            t0 = time.perf_counter()
            retry_after: float | None = None
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    payload = json.load(r)
                return payload, {"attempts": attempts, "last_attempt_ms": round((time.perf_counter() - t0) * 1000)}
            except urllib.error.HTTPError as e:
                raw = e.read().decode("utf-8", errors="replace")[:1000]
                last_err = f"HTTP {e.code}: {raw}"
                if e.code not in RETRY_STATUS or attempt == self.max_retries:
                    raise AdapterError(f"{method} {path} 실패 - {last_err}") from None
                ra = e.headers.get("Retry-After") if e.headers else None
                if ra and ra.strip().isdigit():
                    retry_after = float(ra)
            except (urllib.error.URLError, TimeoutError, ConnectionError, http.client.HTTPException,
                    json.JSONDecodeError) as e:  # ConnectionError - 응답 본문을 읽다 연결이 끊김(2026-10-13 본실험에서 실측)
                last_err = f"{type(e).__name__}: {e}"
                if attempt == self.max_retries:
                    raise AdapterError(f"{method} {path} 실패 - {last_err}") from None
            time.sleep(retry_after if retry_after is not None else min(2.0 * (2**attempt), 30.0))
        raise AdapterError(f"{method} {path} 실패 - {last_err}")  # 도달하지 않음

    # ---- 요청 본문 --------------------------------------------------------

    def build_body(
        self,
        spec: ModelSpec,
        messages: list[dict[str, str]],
        sampling: dict[str, Any],
    ) -> dict:
        """OpenAI 호환 본문 + OpenRouter 확장(provider 라우팅).

        sampling 은 configs 의 동결값(temperature, top_p, max_tokens, seed)을 그대로
        싣는다. 공급사가 지원하지 않는 파라미터는 OpenRouter 가 버리고, 그 사실은
        configs.provider_notes 에 기록한다(실측은 응답 메타데이터로 확인).
        """
        body: dict[str, Any] = {"model": spec.router_slug, "messages": messages}
        for k in ("temperature", "top_p", "max_tokens", "seed"):
            if k in sampling and sampling[k] is not None:
                body[k] = sampling[k]
        provider: dict[str, Any] = {"allow_fallbacks": self.allow_fallbacks}
        if spec.provider_tag:
            provider["order"] = [spec.provider_tag]
        body["provider"] = provider
        # 모델별 추가 필드 - 동결값(model, messages, sampling, provider)은 덮어쓰지 못한다
        for k, v in spec.request_extra.items():
            if k in body:
                raise AdapterError(f"request_extra 가 동결 필드 '{k}' 를 덮어쓰려 한다 ({spec.name})")
            body[k] = v
        return body

    # ---- 호출 -------------------------------------------------------------

    def chat(
        self,
        spec: ModelSpec,
        messages: list[dict[str, str]],
        sampling: dict[str, Any],
        fetch_generation: bool = True,
    ) -> Generation:
        body = self.build_body(spec, messages, sampling)
        t_req = utc_now()
        resp, stats = self._request("POST", "/chat/completions", body)
        t_resp = utc_now()

        # HTTP 200 이어도 본문이 오류이거나(choices 없음) 내용이 비면 실패로 다룬다 -
        # 빈 생성물을 위반 없는 출력으로 채점하는 사고를 막는다.
        choices = resp.get("choices")
        if not choices:
            raise AdapterError(
                f"응답에 choices 가 없다 ({spec.router_slug}); 원본: {json.dumps(resp, ensure_ascii=False)[:1500]}"
            )
        choice = choices[0]
        message = choice.get("message") or {}
        text = message.get("content") or ""
        if not text.strip():
            raise AdapterError(
                f"생성물이 비었다 ({spec.router_slug}); finish_reason={choice.get('finish_reason')}, "
                f"usage={resp.get('usage')}, message keys={list(message.keys())}"
            )
        usage = resp.get("usage") or {}
        reasoning_tokens = (usage.get("completion_tokens_details") or {}).get("reasoning_tokens")

        warnings: list[str] = []
        meta: dict[str, Any] = {
            "model_name": spec.name,
            "router_slug": spec.router_slug,
            "snapshot_frozen": spec.snapshot,
            "provider_tag_requested": spec.provider_tag,
            "allow_fallbacks": self.allow_fallbacks,
            "sampling": {k: body.get(k) for k in ("temperature", "top_p", "max_tokens", "seed")},
            "request_extra": json.loads(json.dumps(spec.request_extra)),
            "request_utc": t_req,
            "response_utc": t_resp,
            "latency_ms": stats["last_attempt_ms"],
            "attempts": stats["attempts"],
            "generation_id": resp.get("id"),
            "model_returned": resp.get("model"),
            "provider_returned": resp.get("provider"),
            "system_fingerprint": resp.get("system_fingerprint"),
            "finish_reason": choice.get("finish_reason"),
            "native_finish_reason": choice.get("native_finish_reason"),
            "usage": {
                "prompt_tokens": usage.get("prompt_tokens"),
                "completion_tokens": usage.get("completion_tokens"),
                "total_tokens": usage.get("total_tokens"),
                "reasoning_tokens": reasoning_tokens,
                # 공급사 프롬프트 캐시 - 같은 요청을 되풀이하면 청구액이 달라져 따로 남긴다(주지 않는 공급사는 None)
                "cached_tokens": (usage.get("prompt_tokens_details") or {}).get("cached_tokens"),
                "cache_write_tokens": (usage.get("prompt_tokens_details") or {}).get("cache_write_tokens"),
                "cost_usd": usage.get("cost"),
            },
            # 추론(reasoning) 모델은 사고 과정을 따로 돌려준다 - 생성물이 아니라 기록만 한다
            "has_reasoning": bool(message.get("reasoning")),
            "generation": None,
            "warnings": warnings,
        }
        if fetch_generation and meta["generation_id"]:
            meta["generation"] = self.get_generation(meta["generation_id"])
            if meta["generation"] is None:
                warnings.append("generation 조회 실패 - 공급사 날짜 판과 실제 비용이 비어 있다")

        self._verify_response(spec, meta)
        return Generation(text=text, meta=meta)

    def _verify_response(self, spec: ModelSpec, meta: dict[str, Any]) -> None:
        """건별 대조 - 추론 토큰 0, 요청한 공급 경로, 동결 snapshot. strict 면 불일치는 오류."""
        problems: list[str] = []
        rt = meta["usage"].get("reasoning_tokens")
        if rt not in (None, 0):
            problems.append(f"reasoning_tokens={rt} (추론 설정이 동결값대로 적용되지 않았다)")
        if spec.provider_tag and meta.get("provider_returned"):
            want = spec.provider_tag.split("/")[0].replace("-", "").lower()
            got = str(meta["provider_returned"]).replace(" ", "").replace("-", "").lower()
            if not (want in got or got in want):
                problems.append(f"공급 경로 불일치: 요청 {spec.provider_tag}, 응답 {meta['provider_returned']}")
        gen = meta.get("generation") or {}
        if spec.snapshot and gen.get("model_dated"):
            v = version_of(gen["model_dated"])
            if v != spec.snapshot:
                problems.append(f"snapshot 불일치: 동결 {spec.snapshot}, 응답 {gen['model_dated']}")
        if not problems:
            return
        meta["warnings"].extend(problems)
        if self.strict:
            kind = SnapshotMismatch if any(p.startswith("snapshot") for p in problems) else AdapterError
            raise kind(f"{spec.router_slug} 응답 대조 실패: " + "; ".join(problems))

    def get_generation(self, generation_id: str, wait_s: float = 2.0) -> dict | None:
        """건별 실제 공급 경로, 날짜 판, 비용. 기록이 몇 초 늦게 생겨 기다렸다 다시 본다 (최대 약 12초).

        조회 자체는 짧게(재시도 1회) 시도한다 - 본 호출과 달리 실패해도 실험을 멈출 일이 아니라서.
        """
        original = self.max_retries
        self.max_retries = 1
        try:
            for attempt in range(3):
                time.sleep(wait_s * (attempt + 1))
                try:
                    d, _ = self._request("GET", f"/generation?id={generation_id}")
                    d = d["data"]
                except (AdapterError, KeyError):
                    continue
                return {
                    "model_dated": d.get("model"),
                    "provider_name": d.get("provider_name"),
                    "upstream_id": d.get("upstream_id"),
                    "total_cost_usd": d.get("total_cost"),
                    "tokens_prompt": d.get("tokens_prompt"),
                    "tokens_completion": d.get("tokens_completion"),
                    "native_tokens_prompt": d.get("native_tokens_prompt"),
                    "native_tokens_completion": d.get("native_tokens_completion"),
                    "native_tokens_cached": d.get("native_tokens_cached"),
                    "cache_discount": d.get("cache_discount"),
                    "generation_time_ms": d.get("generation_time"),
                    "latency_ms": d.get("latency"),
                    "created_at": d.get("created_at"),
                    "finish_reason": d.get("finish_reason"),
                }
            return None
        finally:
            self.max_retries = original

    # ---- snapshot 대조 ----------------------------------------------------

    def get_endpoints(self, router_slug: str) -> dict:
        base = router_slug.split(":", 1)[0]  # ':free', ':batch' 같은 변형 접미사 제거
        d, _ = self._request("GET", f"/models/{base}/endpoints")
        return d["data"]

    def check_snapshot(self, spec: ModelSpec) -> dict:
        """동결 snapshot 과 endpoints 조회를 대조한다. 다르면 SnapshotMismatch.

        대조는 정확 일치다 - 부분 문자열로 하면 날짜 없는 동결값('gemini-2.5-flash-lite')이
        새 날짜 판('...-lite-20260701')에도 통과한다.
        snapshot 이 None 이면 대조를 건너뛰고 그 사실을 반환값에 남긴다 -
        배치 실행기는 None 을 막지 않으므로, 동결 configs 에 새 모델을 더할 때 snapshot 을 꼭 채운다.
        """
        data = self.get_endpoints(spec.router_slug)
        endpoints = data.get("endpoints", [])
        names = [ep.get("name") or "" for ep in endpoints]
        if spec.provider_tag:
            want = spec.provider_tag.split("/")[0]
            tagged = [ep for ep in endpoints if (ep.get("tag") or "").split("/")[0] == want]
            if not tagged:
                raise AdapterError(
                    f"{spec.router_slug}: 공급 경로 '{spec.provider_tag}' 의 endpoint 가 없다 - "
                    f"있는 tag: {sorted({(ep.get('tag') or '') for ep in endpoints})}"
                )
            names_for_tag = [ep.get("name") or "" for ep in tagged]
        else:
            names_for_tag = names

        observed = sorted({v for v in (version_of(n) for n in names_for_tag) if v})
        result = {
            "router_slug": spec.router_slug,
            "provider_tag": spec.provider_tag,
            "snapshot_frozen": spec.snapshot,
            "observed_versions": observed,
            "checked_utc": utc_now(),
            "skipped": spec.snapshot is None,
            "raw_endpoint_names": names,
        }
        if spec.snapshot is None:
            return result
        if not observed:
            raise AdapterError(
                f"endpoints 이름에서 버전을 파싱하지 못했다 ({spec.router_slug}); 원본: {names_for_tag}"
            )
        if spec.snapshot not in observed:
            raise SnapshotMismatch(
                f"{spec.router_slug}: 동결 {spec.snapshot} 이 endpoints 에 없다 - 관측 {observed}"
            )
        return result
