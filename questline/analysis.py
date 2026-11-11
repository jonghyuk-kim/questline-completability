"""본실험 분석 (연구계획서 4.5, 실험 상세 설계 단계 5). 단계 3 에서 고정한다 - 본실험 뒤에는 고치지 않고, 고치면 고친 내용과
이유를 기록하고 고치기 전 결과도 함께 낸다.

입력은 배치의 채점표(scores.jsonl - questline.score.score_cell 의 행)와, 죽음 함정 분류에만 쓰는 생성물(cells.jsonl)이다.

  기초 통계   조건, 모델, 함정 종류, 오류 유형별 비율과 라인 군집 부트스트랩 95% 신뢰구간(퍼센타일, 2000회, seed 고정)
  RQ1         C1 출력의 함정 지점 오류율(판정 불가 제외)과 모델별 판정 불가 비율. 오류 유형의 분모는 그 유형이 걸리는
              함정 종류의 판정된 함정이다(잘못된 출처, 획득 단계 누락은 소유 함정, 죽은 인물 참여는 죽음 함정)
  H4          C1 함정 지점 단위, 오류 유무 ~ 함정 종류 + 모델, 라인 군집 GEE. 효과는 소유 대 죽음 로그 오즈비
  H4 탐색     같은 자료에 함정 종류 × 모델 상호작용을 넣은 모형. 모델별 소유 대 죽음 로그 오즈비와 상호작용 항의
              결합 Wald 검정(자유도 = 모델 수 − 1). 가설 검정이 아니라 BH 묶음에 넣지 않는다(analysis-v2 에서 더함 -
              예비 측정에서 GPT 만 죽음 함정 오류가 더 많아 평균 차이만으로는 모델별 방향을 볼 수 없다)
  거리 탐색   C1 함정 지점의 상태 변화와 함정 사이 거리(퀘스트 수, questline.lines.probe_distances)별 오류율과,
              오류 유무 ~ 함정 종류 + 모델 + 거리(연속) 라인 군집 GEE 의 거리 계수(퀘스트 하나 멀어질 때의 로그 오즈비).
              모델이 바뀌어도 쓸 수 있는 "언제 틀리나"를 보려는 탐색이라 BH 묶음에 넣지 않는다(analysis-v4 에서 더함)
  죽음 민감도  C1 죽음 함정의 물은 인물 ①~④ 분류(death_class)와, ③을 판정 불가로 돌린 오류율
  H1, H2      셀 단위, 진행 가능 여부 ~ 조건(C2 기준) + 모델, 라인 군집 GEE. 효과는 C2 대 C1, C2 대 C3 로그 오즈비
  BH          H1, H2, H4 의 양측 p 를 한 묶음으로 Benjamini-Hochberg 보정. 보정 p < 0.05 이고 효과가 가설 방향(양수)이면 지지
  H3          조건 × 모델 상호작용 모형에서 모델별 C2 대 C1 효과. 세 점추정이 모두 양수(개선 방향)면 지지
  RQ3         조건별 비용, 지연, 재생성 횟수의 셀 평균과 진행 가능 출력당 비용(조건 총비용 ÷ 진행 가능 셀 수).
              주 비용은 정가 비용(cost_list_usd - 호출마다 토큰 수 × configs 의 price_usd_per_mtok, list_cost)이고
              청구액(cost_usd)은 보조다. 청구액은 공급사 프롬프트 캐시 때문에 같은 요청도 먼저 보낸 조건(배치는 늘 C1 이
              먼저)만 제값을 내 조건 비교를 흐린다(analysis-v2 에서 바꿈).
              가격이 바뀌어도 쓸 수 있게 진행 가능 출력당 호출 수(calls)와 토큰 수(tokens - 입력 + 출력)를 함께 내고,
              진행 가능 출력당 정가 비용, 호출 수, 토큰 수의 조건 사이 비율(C2/C1, C2/C3)을 라인 군집 부트스트랩
              구간과 함께 낸다(analysis-v3 에서 더함)
  조작 점검    조건별 퀘스트당 단계 수(셀 평균)와 개요 결과 달성률(이룬 결과 합 ÷ 결과 합)

GEE 는 로짓 연결, 교환 가능 상관, 편향 보정 표준오차(bias_reduced)로 검정력 모의(analysis/power_questline.py)와 같다.
드문 사건 대비 규칙: 설명변수 칸(범주 조합) 가운데 결과가 모두 0 이거나 모두 1 인 칸이 있고 GEE 가 실패하면(예외,
수렴 경고, 유한하지 않은 추정값이나 표준오차, 절댓값 10 을 넘는 계수 - 분리로 발산한 것), 같은 설명변수 구조를 계수 사전분포 N(0, 2.5²), 라인 임의효과의
베이즈 로지스틱 혼합모형(statsmodels BinomialBayesMixedGLM, 변분 추정 - 시작값 난수 seed 고정)으로 추정한다. 사후분포를 정규로 근사해
평균 ± 1.96 표준편차를 구간으로, 2·(1 − Φ(|평균/표준편차|)) 를 BH 에 넣는 p 로 쓴다. 변분 추정은 계수끼리 독립으로 두므로
대비(H3)의 분산은 계수 분산의 합이다. 칸이 비지 않았는데 GEE 가 실패하면 대체하지 않고 실패로 보고한다(연구자와 정한다).
"""
from __future__ import annotations

import math
import re
import warnings
from collections import Counter, defaultdict

import numpy as np

from questline.checker import Index, _quest_for
from questline.lines import name_forms

CONDS = ("C1", "C2", "C3")
STATE_TYPES = {"wrong_source": ("R4", "custody"), "missing_acquire": ("R6", "custody"), "dead_npc": ("R2", "death")}
ALPHA = 0.05
N_BOOT = 2000
BOOT_SEED = 20261012
FE_PRIOR_SD = 2.5
MAX_ABS_COEF = 10.0  # 로그 오즈비 10 = 오즈비 약 22000. 넘으면 분리로 발산한 것으로 보고 수렴 실패로 센다


# ---------- 죽음 함정 분류 (상세 설계 단계 3 작업 6, 단계 5 의 민감도 분석) ----------

def list_cost(attempts: list[dict], price: dict) -> float:
    """셀의 정가 비용 - 시도마다 (입력 토큰 × 입력 정가 + 출력 토큰 × 출력 정가), 정가는 백만 토큰당 달러."""
    total = 0.0
    for a in attempts:
        u = (a.get("meta") or {}).get("usage") or {}
        if u.get("prompt_tokens") is None or u.get("completion_tokens") is None:
            raise ValueError(f"시도 {a.get('t')} 에 토큰 수가 없다 - 정가 비용을 낼 수 없다")
        total += (u["prompt_tokens"] * price["input"] + u["completion_tokens"] * price["output"]) / 1e6
    return total


def cell_tokens(attempts: list[dict]) -> int:
    """셀의 토큰 수 - 시도마다 입력 + 출력 토큰의 합."""
    total = 0
    for a in attempts:
        u = (a.get("meta") or {}).get("usage") or {}
        if u.get("prompt_tokens") is None or u.get("completion_tokens") is None:
            raise ValueError(f"시도 {a.get('t')} 에 토큰 수가 없다")
        total += u["prompt_tokens"] + u["completion_tokens"]
    return total


def death_class(line: dict, quests, status: str, qn: int, ix: Index) -> str:
    """C1 죽음 함정 하나의 분류. ① 오류 ② 대답자 ③ 개요에 나온 다른 산 인물 ④ 나머지, 판정 불가는 '-'."""
    if status == "error":
        return "1"
    if status != "kept":
        return "-"
    q = _quest_for(quests if isinstance(quests, list) else [], qn) or {}
    npcs = {e["id"] for s in (q.get("steps") or []) if isinstance(s, dict) and (e := ix.resolve(s.get("npc")))}
    if npcs & set(line.get("death_answerers") or []):
        return "2"
    briefs = " ".join(x["brief"] for x in line["quests"])
    if any(named_in(briefs, n, ix) for n in npcs):
        return "3"
    return "4"


def named_in(text: str, eid: str, ix: Index) -> bool:
    """text 에 그 인물의 이름이 나오는가. 다른 존재의 더 긴 이름 안에 든 경우는 뺀다("하렌드 발크" 안의 "하렌")."""
    longer = [(m.start(), m.start() + len(g)) for o, e in ix.ent.items() if o != eid
              for g in name_forms(e) for m in re.finditer(re.escape(g), text)]
    for f in name_forms(ix.ent[eid]):
        for m in re.finditer(re.escape(f), text):
            a, b = m.span()
            if not any(s <= a and b <= t and t - s > b - a for s, t in longer):
                return True
    return False


# ---------- 라인 군집 부트스트랩 ----------

def ratio_ci(units: list[tuple[str, float, float]], n_boot: int = N_BOOT, seed: int = BOOT_SEED) -> dict:
    """units: (라인, 분자, 분모). 라인을 복원 추출해 Σ분자 / Σ분모 의 퍼센타일 95% 구간을 낸다."""
    num, den = defaultdict(float), defaultdict(float)
    for line, a, b in units:
        num[line] += a
        den[line] += b
    keys = sorted(den)
    tot_n, tot_d = sum(num.values()), sum(den.values())
    out = {"num": tot_n, "den": tot_d, "est": tot_n / tot_d if tot_d else None, "lo": None, "hi": None}
    if not keys or not tot_d:
        return out
    a, b = np.array([num[k] for k in keys]), np.array([den[k] for k in keys])
    idx = np.random.default_rng(seed).integers(len(keys), size=(n_boot, len(keys)))
    sa, sb = a[idx].sum(1), b[idx].sum(1)
    r = sa[sb > 0] / sb[sb > 0]
    out["lo"], out["hi"] = float(np.percentile(r, 2.5)), float(np.percentile(r, 97.5))
    return out


def per_success_ratio(rows: list[dict], field: str, a: str, b: str, n_boot: int = N_BOOT, seed: int = BOOT_SEED) -> dict:
    """(조건 a 의 Σfield ÷ 진행 가능 셀 수) ÷ (조건 b 의 같은 값). 라인을 복원 추출해 퍼센타일 95% 구간을 낸다."""
    lines = sorted({r["line_id"] for r in rows})
    pos = {l: i for i, l in enumerate(lines)}
    m = np.zeros((4, len(lines)))  # a 의 field, a 의 진행 가능, b 의 field, b 의 진행 가능
    for r in rows:
        if r["condition"] in (a, b):
            k = 0 if r["condition"] == a else 2
            m[k, pos[r["line_id"]]] += r[field]
            m[k + 1, pos[r["line_id"]]] += r["final_completable"]

    def ratio(t):
        return (t[0] / t[1]) / (t[2] / t[3]) if t[1] and t[3] and t[2] else None

    out = {"est": ratio(m.sum(1)), "lo": None, "hi": None}
    if out["est"] is None:
        return out
    idx = np.random.default_rng(seed).integers(len(lines), size=(n_boot, len(lines)))
    t = m[:, idx].sum(2)
    ok = (t[1] > 0) & (t[3] > 0) & (t[2] > 0)
    r = (t[0, ok] / t[1, ok]) / (t[2, ok] / t[3, ok])
    out["lo"], out["hi"] = float(np.percentile(r, 2.5)), float(np.percentile(r, 97.5))
    return out


# ---------- 모형 적합 (GEE, 드문 사건 대비) ----------

def _norm_p(z: float) -> float:
    return math.erfc(abs(z) / math.sqrt(2))


def _has_empty_cell(y, cells) -> bool:
    by = defaultdict(list)
    for v, c in zip(y, cells):
        by[c].append(v)
    return any(min(v) == max(v) for v in by.values())


def fit_logit(y, X, groups, names: list[str], cells) -> dict:
    """y 0/1, X 설계행렬(첫 열 상수), groups 라인, cells 행마다 설명변수 칸. 반환: method, names, params, cov."""
    import statsmodels.api as sm
    from statsmodels.genmod.cov_struct import Exchangeable
    from statsmodels.tools.sm_exceptions import ConvergenceWarning

    y, X = np.asarray(y, float), np.asarray(X, float)
    empty = _has_empty_cell(y, cells)
    reason = None
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            warnings.simplefilter("error", ConvergenceWarning)
            res = sm.GEE(y, X, groups=np.asarray(groups), family=sm.families.Binomial(),
                         cov_struct=Exchangeable()).fit(cov_type="bias_reduced")
        b, V = np.asarray(res.params), np.asarray(res.cov_params())
        if not (np.all(np.isfinite(b)) and np.all(np.isfinite(V)) and np.all(np.diag(V) > 0)):
            reason = "유한하지 않은 추정값이나 표준오차"
        elif np.max(np.abs(b)) > MAX_ABS_COEF:
            reason = f"계수 발산(|계수| {np.max(np.abs(b)):.1f} > {MAX_ABS_COEF})"
    except ConvergenceWarning as e:
        reason = f"수렴 경고: {e}"
    except Exception as e:  # noqa: BLE001 - 어떤 실패든 기록하고 규칙대로 처리한다
        reason = f"{type(e).__name__}: {e}"
    if reason is None:
        return {"method": "GEE", "names": names, "b": b.tolist(), "cov": V.tolist(), "empty_cell": empty}
    if not empty:
        return {"method": "failed", "names": names, "reason": reason, "empty_cell": False}
    from statsmodels.genmod.bayes_mixed_glm import BinomialBayesMixedGLM
    lines = sorted(set(groups))
    Z = np.array([[g == l for l in lines] for g in groups], float)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        r = BinomialBayesMixedGLM(y, X, Z, np.zeros(len(lines), int), fe_p=FE_PRIOR_SD).fit_vb(rng=BOOT_SEED)
    return {"method": "bayes", "names": names, "b": list(map(float, r.fe_mean)),
            "cov": np.diag(np.asarray(r.fe_sd) ** 2).tolist(), "empty_cell": True, "gee_failure": reason}


def contrast(fit: dict, weights: dict[str, float]) -> dict:
    """계수의 선형결합. weights 이름 → 가중치. 반환: est, se, lo, hi, p (정규 근사)."""
    if fit["method"] == "failed":
        return {"est": None, "se": None, "lo": None, "hi": None, "p": None}
    c = np.array([weights.get(n, 0.0) for n in fit["names"]])
    b, V = np.array(fit["b"]), np.array(fit["cov"])
    est, se = float(c @ b), float(math.sqrt(c @ V @ c))
    return {"est": est, "se": se, "lo": est - 1.96 * se, "hi": est + 1.96 * se, "p": _norm_p(est / se)}


def wald(fit: dict, terms: list[str]) -> dict:
    """계수 여럿이 모두 0 인지의 결합 Wald 검정. 반환: chi2, df, p."""
    if fit["method"] == "failed" or not terms:  # 항이 없으면(모델이 하나) 검정하지 않는다
        return {"chi2": None, "df": len(terms), "p": None}
    from scipy.stats import chi2
    idx = [fit["names"].index(t) for t in terms]
    b, V = np.array(fit["b"])[idx], np.array(fit["cov"])[np.ix_(idx, idx)]
    stat = float(b @ np.linalg.solve(V, b))
    return {"chi2": stat, "df": len(terms), "p": float(chi2.sf(stat, len(terms)))}


def bh(ps: list[float]) -> list[float]:
    """Benjamini-Hochberg 보정 p."""
    m = len(ps)
    order = sorted(range(m), key=lambda i: ps[i])
    adj, prev = [0.0] * m, 1.0
    for rank in range(m, 0, -1):
        i = order[rank - 1]
        prev = min(prev, ps[i] * m / rank)
        adj[i] = prev
    return adj


# ---------- 분석 ----------

def _design(rows, factors: list[tuple[str, list[str], str]]):
    """factors: (이름, 수준 목록 - 첫 수준이 기준, 행에서 값을 꺼낼 키). 반환: X, names."""
    names = ["const"] + [f"{n}[{lv}]" for n, levels, _ in factors for lv in levels[1:]]
    X = [[1.0] + [float(r[key] == lv) for _, levels, key in factors for lv in levels[1:]] for r in rows]
    return X, names


def probe_units(rows: list[dict], condition: str = "C1") -> list[dict]:
    """함정 지점 단위 행. 판정 불가 포함 - status 로 거른다."""
    out = []
    for r in rows:
        if r["condition"] != condition:
            continue
        for qn, pr in r["final_probes"].items():
            out.append({"line": r["line_id"], "model": r["model"], "rep": r["rep"], "quest": int(qn), "type": pr["type"],
                        "status": pr["status"], "rules": pr["rules"]})
    return out


def analyze(rows: list[dict], death_classes: list[dict] | None = None,
            probe_dist: dict[tuple[str, int], int | None] | None = None) -> dict:
    """rows: 채점표 행 전부(행마다 정가 비용 cost_list_usd 를 붙여 넣는다 - list_cost). death_classes: C1 죽음 함정마다
    {line, class}(death_class 결과), 없으면 민감도를 건너뛴다. probe_dist: (라인, 함정 퀘스트 번호) → 거리
    (questline.lines.probe_distances), 없으면 거리 탐색을 건너뛴다."""
    for k in ("cost_list_usd", "calls", "tokens"):
        if any(k not in r for r in rows):
            raise ValueError(f"행에 {k} 가 없다 - cells.jsonl 의 시도로 붙인다(list_cost, 시도 수, cell_tokens)")
    models = sorted({r["model"] for r in rows})
    res: dict = {"cells": len(rows), "lines": len({r["line_id"] for r in rows}), "models": models}

    # 기초 통계 - 조건별(마지막 출력)
    desc = {}
    for c in CONDS:
        rs = [r for r in rows if r["condition"] == c]
        d = {"completable": ratio_ci([(r["line_id"], r["final_completable"], 1) for r in rs]),
             "static_error": ratio_ci([(r["line_id"], r["final_static_violations"] > 0, 1) for r in rs]),
             "by_model": {m: ratio_ci([(r["line_id"], r["final_completable"], 1) for r in rs if r["model"] == m])
                          for m in models}}
        pu = probe_units(rows, c)
        d["probe_error"] = {t: ratio_ci([(u["line"], u["status"] == "error", 1) for u in pu
                                         if u["type"] == t and u["status"] != "undetermined"]) for t in ("custody", "death")}
        desc[c] = d
    res["descriptive"] = desc

    # RQ1 - C1 함정 지점
    pu = probe_units(rows, "C1")
    det = [u for u in pu if u["status"] != "undetermined"]
    rq1 = {"by_type": {t: ratio_ci([(u["line"], u["status"] == "error", 1) for u in det if u["type"] == t])
                       for t in ("custody", "death")},
           "by_model_type": {f"{m}/{t}": ratio_ci([(u["line"], u["status"] == "error", 1) for u in det
                                                   if u["type"] == t and u["model"] == m])
                             for m in models for t in ("custody", "death")},
           "by_error_type": {et: ratio_ci([(u["line"], u["status"] == "error" and rule in u["rules"], 1) for u in det
                                           if u["type"] == pt]) for et, (rule, pt) in STATE_TYPES.items()},
           "undetermined_by_model": {m: ratio_ci([(u["line"], u["status"] == "undetermined", 1) for u in pu
                                                  if u["model"] == m]) for m in models}}
    res["rq1"] = rq1

    # H4
    X, names = _design(det, [("type", ["death", "custody"], "type"), ("model", models, "model")])
    f4 = fit_logit([u["status"] == "error" for u in det], X, [u["line"] for u in det], names,
                   [(u["type"], u["model"]) for u in det])
    h4 = contrast(f4, {"type[custody]": 1.0})

    # H4 탐색 - 함정 종류 × 모델
    X, names = _design(det, [("type", ["death", "custody"], "type"), ("model", models, "model")])
    for m in models[1:]:
        names.append(f"type[custody]:model[{m}]")
        for row, u in zip(X, det):
            row.append(float(u["type"] == "custody" and u["model"] == m))
    f4x = fit_logit([u["status"] == "error" for u in det], X, [u["line"] for u in det], names,
                    [(u["type"], u["model"]) for u in det])
    res["h4_by_model"] = {
        "method": f4x["method"], "fit": f4x, "interaction": wald(f4x, [f"type[custody]:model[{m}]" for m in models[1:]]),
        "by_model": {m: contrast(f4x, {"type[custody]": 1.0} | ({f"type[custody]:model[{m}]": 1.0} if m != models[0] else {}))
                     for m in models}}

    # 거리 탐색
    if probe_dist is not None:
        du = [u | {"dist": probe_dist.get((u["line"], u["quest"]))} for u in det]
        du = [u for u in du if u["dist"] is not None]
        res["distance"] = {
            "by_type_distance": {f"{t}/{d}": ratio_ci([(u["line"], u["status"] == "error", 1) for u in du
                                                        if u["type"] == t and u["dist"] == d])
                                 for t in ("custody", "death") for d in sorted({u["dist"] for u in du if u["type"] == t})}}
        X, names = _design(du, [("type", ["death", "custody"], "type"), ("model", models, "model")])
        names.append("distance")
        for row, u in zip(X, du):
            row.append(float(u["dist"]))
        fd = fit_logit([u["status"] == "error" for u in du], X, [u["line"] for u in du], names,
                       [(u["type"], u["model"], u["dist"]) for u in du])
        res["distance"] |= {"trend": contrast(fd, {"distance": 1.0}), "method": fd["method"], "fit": fd}

    # 죽음 함정 민감도
    if death_classes is not None:
        n = Counter(d["class"] for d in death_classes)
        kept = n["2"] + n["3"] + n["4"]
        res["death_sensitivity"] = {
            "counts": dict(n), "q3_of_kept": n["3"] / kept if kept else None,
            "error_rate": n["1"] / (n["1"] + kept) if n["1"] + kept else None,
            "error_rate_q3_undetermined": n["1"] / (n["1"] + n["2"] + n["4"]) if n["1"] + n["2"] + n["4"] else None}

    # H1, H2
    X, names = _design(rows, [("cond", ["C2", "C1", "C3"], "condition"), ("model", models, "model")])
    y = [r["final_completable"] for r in rows]
    g = [r["line_id"] for r in rows]
    cells = [(r["condition"], r["model"]) for r in rows]
    f12 = fit_logit(y, X, g, names, cells)
    h1 = contrast(f12, {"cond[C1]": -1.0})
    h2 = contrast(f12, {"cond[C3]": -1.0})

    # BH
    tests = {"H1": h1, "H2": h2, "H4": h4}
    valid = [k for k, v in tests.items() if v["p"] is not None]
    adj = dict(zip(valid, bh([tests[k]["p"] for k in valid])))
    for k, v in tests.items():
        v["p_adj"] = adj.get(k)
        v["supported"] = None if v["p"] is None else bool(adj[k] < ALPHA and v["est"] > 0)
    res["h4"] = h4 | {"method": f4["method"], "fit": f4}
    res["h1"] = h1 | {"method": f12["method"]}
    res["h2"] = h2 | {"method": f12["method"]}
    res["fit_h12"] = f12

    # H3 - 조건 × 모델
    base = [("cond", ["C2", "C1", "C3"], "condition"), ("model", models, "model")]
    X, names = _design(rows, base)
    for cl in ("C1", "C3"):
        for m in models[1:]:
            names.append(f"cond[{cl}]:model[{m}]")
            for row, r in zip(X, rows):
                row.append(float(r["condition"] == cl and r["model"] == m))
    f3 = fit_logit(y, X, g, names, cells)
    per = {m: contrast(f3, {"cond[C1]": -1.0} | ({f"cond[C1]:model[{m}]": -1.0} if m != models[0] else {}))
           for m in models}
    ests = [v["est"] for v in per.values()]
    res["h3"] = {"method": f3["method"], "by_model": per, "fit": f3,
                 "supported": None if None in ests else all(e > 0 for e in ests)}

    # RQ3, 조작 점검
    rq3, manip = {}, {}
    for c in CONDS:
        rs = [r for r in rows if r["condition"] == c]
        rq3[c] = {k: ratio_ci([(r["line_id"], r[f], 1) for r in rs])
                  for k, f in (("cost_list_usd", "cost_list_usd"), ("cost_billed_usd", "cost_usd"),
                               ("latency_s", "latency_s"), ("regenerations", "regenerations"))}
        rq3[c]["cost_per_completable_list"] = ratio_ci([(r["line_id"], r["cost_list_usd"], r["final_completable"]) for r in rs])
        rq3[c]["cost_per_completable_billed"] = ratio_ci([(r["line_id"], r["cost_usd"], r["final_completable"]) for r in rs])
        rq3[c]["calls_per_completable"] = ratio_ci([(r["line_id"], r["calls"], r["final_completable"]) for r in rs])
        rq3[c]["tokens_per_completable"] = ratio_ci([(r["line_id"], r["tokens"], r["final_completable"]) for r in rs])
        manip[c] = {"steps_per_quest": ratio_ci([(r["line_id"], r["final_steps_per_quest"], 1) for r in rs
                                                 if r["final_steps_per_quest"] is not None]),
                    "goals_met": ratio_ci([(r["line_id"], r["final_goals_met"], r["final_goals_total"]) for r in rs])}
    res["rq3"], res["manipulation"] = rq3, manip
    res["rq3_ratio"] = {f"{a}/{b}": {k: per_success_ratio(rows, f, a, b)
                                    for k, f in (("cost_list", "cost_list_usd"), ("calls", "calls"), ("tokens", "tokens"))}
                        for a, b in (("C2", "C1"), ("C2", "C3"))}
    return res
