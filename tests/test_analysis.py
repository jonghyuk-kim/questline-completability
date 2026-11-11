"""분석 모듈 (questline/analysis.py) - 보정, 부트스트랩, 드문 사건 대비 규칙, 끝까지 돌아가는지."""
import numpy as np
import pytest
from statsmodels.stats.multitest import multipletests

from questline.analysis import analyze, bh, cell_tokens, fit_logit, list_cost, per_success_ratio, ratio_ci, wald

MODELS = ("claude", "gemini", "gpt")


def test_bh_matches_statsmodels():
    ps = [0.01, 0.04, 0.03, 0.2, 0.0001]
    assert bh(ps) == pytest.approx(list(multipletests(ps, method="fdr_bh")[1]))


def test_ratio_ci_is_deterministic_and_covers_estimate():
    units = [(f"L{i % 7}", i % 3 == 0, 1) for i in range(60)]
    a, b = ratio_ci(units), ratio_ci(units)
    assert a == b
    assert a["est"] == pytest.approx(20 / 60)
    assert a["lo"] <= a["est"] <= a["hi"]


def test_list_cost_uses_tokens_and_list_price():
    att = [{"t": 0, "meta": {"usage": {"prompt_tokens": 15830, "completion_tokens": 953, "cost_usd": 0.00246}}},
           {"t": 1, "meta": {"usage": {"prompt_tokens": 17000, "completion_tokens": 1000, "cost_usd": 0.0007}}}]
    assert list_cost(att, {"input": 0.10, "output": 0.50}) == pytest.approx((15830 + 17000) * 0.1e-6 + (953 + 1000) * 0.5e-6)
    with pytest.raises(ValueError):
        list_cost([{"t": 0, "meta": {"usage": {"prompt_tokens": None, "completion_tokens": 5}}}], {"input": 1, "output": 1})


def test_cell_tokens_sums_input_and_output():
    att = [{"t": 0, "meta": {"usage": {"prompt_tokens": 100, "completion_tokens": 20}}},
           {"t": 1, "meta": {"usage": {"prompt_tokens": 150, "completion_tokens": 30}}}]
    assert cell_tokens(att) == 300


def test_per_success_ratio_point_and_interval():
    rows = []
    for i in range(10):
        rows += [{"line_id": f"L{i}", "condition": "C2", "calls": 2, "final_completable": True},
                 {"line_id": f"L{i}", "condition": "C3", "calls": 2, "final_completable": i % 2 == 0}]
    r = per_success_ratio(rows, "calls", "C2", "C3")
    assert r["est"] == pytest.approx((20 / 10) / (20 / 5))  # 성공 한 번에 드는 호출이 C2 가 절반
    assert r["lo"] <= r["est"] <= r["hi"]
    assert per_success_ratio(rows, "calls", "C2", "C3") == r  # seed 고정


def test_wald_matches_single_term_z_test():
    fit = {"method": "GEE", "names": ["const", "a", "b"], "b": [0.1, 0.6, -0.2],
           "cov": [[0.04, 0, 0], [0, 0.09, 0.01], [0, 0.01, 0.16]]}
    one = wald(fit, ["a"])
    assert one["df"] == 1 and one["chi2"] == pytest.approx((0.6 / 0.3) ** 2)
    two = wald(fit, ["a", "b"])
    V = np.array([[0.09, 0.01], [0.01, 0.16]])
    assert two["df"] == 2 and two["chi2"] == pytest.approx(float(np.array([0.6, -0.2]) @ np.linalg.solve(V, [0.6, -0.2])))
    assert wald({"method": "failed"}, ["a"])["p"] is None
    assert wald(fit, []) == {"chi2": None, "df": 0, "p": None}  # 모델이 하나면 상호작용 항이 없다


def test_rows_without_list_cost_are_rejected():
    rows = _rows({"C1": 0.5, "C2": 0.5, "C3": 0.5}, n_lines=3)
    for k in ("cost_list_usd", "calls", "tokens"):
        bad = [dict(r) for r in rows]
        del bad[0][k]
        with pytest.raises(ValueError, match=k):
            analyze(bad)


def _rows(p: dict[str, float], n_lines=12, reps=3, seed=0, probe_p=(0.4, 0.2), flip=None):
    """flip: 이 모델은 소유와 죽음 함정 오류율을 바꿔 쓴다(함정 종류 × 모델 상호작용)."""
    rng = np.random.default_rng(seed)
    rows = []
    for l in range(n_lines):
        for m in MODELS:
            for c in ("C1", "C2", "C3"):
                for r in range(1, reps + 1):
                    ok = bool(rng.random() < p[c])
                    pc, pd_ = probe_p[::-1] if m == flip else probe_p
                    probes = {str(q): {"type": t, "status": "error" if rng.random() < pp else "kept", "rules": []}
                              for q, t, pp in ((3, "custody", pc), (4, "custody", pc), (5, "death", pd_))}
                    for pr in probes.values():
                        pr["error"] = pr["status"] == "error"
                        if pr["error"]:
                            pr["rules"] = ["R4"] if pr["type"] == "custody" else ["R2"]
                    rows.append({"line_id": f"M{l:02d}", "model": m, "condition": c, "rep": r, "final_completable": ok,
                                 "final_static_violations": 0, "final_probes": probes, "cost_usd": 0.003, "cost_list_usd": 0.004, "calls": 1 if c == "C1" else 2, "tokens": 17000 if c == "C1" else 34000,
                                 "latency_s": 9.0, "regenerations": 0 if c == "C1" else 1, "final_steps_per_quest": 3.0,
                                 "final_goals_met": 4, "final_goals_total": 4})
    return rows


def test_analyze_runs_end_to_end_and_detects_strong_effects():
    res = analyze(_rows({"C1": 0.25, "C2": 0.9, "C3": 0.5}, n_lines=20, probe_p=(0.5, 0.1)),
                  [{"line": "M00", "class": x} for x in "12234-"])
    assert res["h1"]["method"] == "GEE" and res["h1"]["supported"] is True
    assert res["h2"]["supported"] is True
    assert res["h4"]["supported"] is True and res["h4"]["est"] > 0
    assert res["h3"]["supported"] is True
    assert set(res["rq3"]) == {"C1", "C2", "C3"}
    assert res["rq3"]["C1"]["cost_list_usd"]["est"] == pytest.approx(0.004)
    assert res["rq3"]["C1"]["cost_billed_usd"]["est"] == pytest.approx(0.003)
    c1, c2 = res["rq3"]["C1"], res["rq3"]["C2"]
    assert c2["calls_per_completable"]["est"] == pytest.approx(2 / c2_rate(res)) and c1["tokens_per_completable"]["est"] > 0
    rr = res["rq3_ratio"]["C2/C1"]["calls"]
    assert rr["est"] == pytest.approx((2 / c2_rate(res)) / (1 / res["descriptive"]["C1"]["completable"]["est"]))
    hx = res["h4_by_model"]
    assert hx["method"] == "GEE" and set(hx["by_model"]) == set(MODELS) and hx["interaction"]["df"] == 2
    assert all(v["est"] > 0 for v in hx["by_model"].values())
    ds = res["death_sensitivity"]
    assert ds["error_rate"] == pytest.approx(1 / 5) and ds["error_rate_q3_undetermined"] == pytest.approx(1 / 4)


def c2_rate(res):
    return res["descriptive"]["C2"]["completable"]["est"]


def test_null_effect_is_not_supported():
    res = analyze(_rows({"C1": 0.6, "C2": 0.6, "C3": 0.6}, n_lines=20, seed=3, probe_p=(0.3, 0.3)))
    assert res["h1"]["supported"] is False and res["h2"]["supported"] is False and res["h4"]["supported"] is False


def test_empty_cell_with_separation_falls_back_to_bayes():
    # C2 가 모두 진행 가능(빈 칸)하고 C1 은 모두 실패 - GEE 가 발산한다
    rows = _rows({"C1": 0.0, "C2": 1.0, "C3": 0.5}, n_lines=10)
    res = analyze(rows)
    assert res["h1"]["method"] == "bayes"
    assert res["fit_h12"]["gee_failure"]
    assert res["h1"]["est"] > 0 and np.isfinite(res["h1"]["p"])


def test_gee_failure_without_empty_cell_is_reported_not_replaced():
    y = [1, 0] * 5
    X = [[1.0, 1.0]] * 10  # 같은 열 둘 - 특이행렬
    fit = fit_logit(y, X, [f"L{i // 2}" for i in range(10)], ["const", "dup"], ["a"] * 10)
    assert fit["method"] == "failed" and not fit["empty_cell"]


def test_h4_interaction_detects_model_with_reversed_direction():
    res = analyze(_rows({"C1": 0.4, "C2": 0.8, "C3": 0.5}, n_lines=30, seed=5, probe_p=(0.5, 0.15), flip="gpt"))
    hx = res["h4_by_model"]
    assert hx["by_model"]["gpt"]["est"] < 0 < hx["by_model"]["claude"]["est"]
    assert hx["interaction"]["p"] < 0.05
    # 탐색 분석은 BH 묶음 밖 - 묶음은 H1, H2, H4 셋 그대로
    assert all(res[k]["p_adj"] is not None for k in ("h1", "h2", "h4")) and "p_adj" not in hx


def test_distance_trend_detects_errors_growing_with_distance():
    rows = _rows({"C1": 0.4, "C2": 0.8, "C3": 0.5}, n_lines=30, seed=7)
    rng = np.random.default_rng(11)
    dist = {}
    for r in rows:  # 거리를 함정마다 정하고, C1 의 오류를 거리에 따라 다시 뽑는다
        for qn, pr in r["final_probes"].items():
            d = dist.setdefault((r["line_id"], int(qn)), int(rng.integers(1, 5)))
            if r["condition"] == "C1":
                pr["status"] = "error" if rng.random() < 0.1 + 0.18 * (d - 1) else "kept"
                pr["error"] = pr["status"] == "error"
                pr["rules"] = (["R4"] if pr["type"] == "custody" else ["R2"]) if pr["error"] else []
    res = analyze(rows, None, dist)
    t = res["distance"]["trend"]
    assert res["distance"]["method"] == "GEE" and t["est"] > 0 and t["p"] < 0.05
    assert "custody/1" in res["distance"]["by_type_distance"]
    assert "distance" not in analyze(rows)  # 거리를 주지 않으면 건너뛴다


def test_named_in_skips_name_inside_longer_name():
    """죽음 민감도 ③ - 다른 인물의 더 긴 이름 안에 든 이름은 개요에 나온 것으로 세지 않는다(M13 "하렌드 발크" 안의 "하렌")."""
    import json
    from pathlib import Path
    from questline.analysis import named_in
    from questline.checker import Index
    ix = Index(json.loads((Path(__file__).resolve().parent.parent / "worldbible/worldbible_v1.json").read_text()))
    assert not named_in("기사단장 하렌드 발크가 전사하고", "haren", ix)
    assert named_in("기사단장 하렌드 발크가 전사하고", "harend", ix)
    assert named_in("대장장이 하렌에게 묻는다", "haren", ix)
