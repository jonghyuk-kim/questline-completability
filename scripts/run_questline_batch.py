"""퀘스트 라인 배치 실행기 - 라인 × 모델 × 조건 × 반복 셀을 생성하고 채점한다 (실험 상세 설계 단계 2~4).

    .venv/bin/python scripts/run_questline_batch.py --lines scenarios/questlines_pre.yaml --batch pre1 \
        [--worldbible worldbible/worldbible_v1.json] [--models gpt,claude,gemini] [--conditions C1,C2,C3 (탐색 조건 C4 는 지정할 때만)] \
        [--reps 1] [--line-ids P01,P02] [--cost-cap 60] [--probe-mix custody=2,death=1] [--dry-run]

라인 형식 검사에서 라인마다 함정 배분(기본 소유 2, 죽음 1)도 본다. 배분이 다른 시험 라인은 --probe-mix none 으로 돌린다.

산출물 runs/questline/<batch>/ (git 으로 보존 - 배치가 끝난 뒤 커밋한다)
    cells.jsonl    셀마다 시도 전부(출력 원문, 파싱한 quests, 위반, 호출 meta)
    scores.jsonl   셀마다 채점 행 (questline.score)
    manifest_<UTC>.json  실행 인자, 레포 커밋, 모델 날짜 판 대조 결과
    errors.jsonl   호출 오류로 끝나지 못한 셀 - 다시 실행하면 그 셀부터 이어 간다

순서는 반복 → 라인 → 모델 → 조건이다. 도중에 멈춰도 앞 반복은 모든 조건이 고르게 채워져 있다.
실행 전에 모델마다 endpoints 조회로 동결 날짜 판을 대조하고, 다르면 멈춘다(README 불변식).
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

from pipeline.generators import DEFAULT_CONFIG, AdapterError, ModelSpec, OpenRouterClient, load_config, utc_now  # noqa: E402
from questline.checker import Index  # noqa: E402
from questline.lines import PROBE_MIX, load_lines, parse_probe_mix, validate_lines  # noqa: E402
from questline.run import ALL_CONDITIONS, CONDITIONS, run_cell  # noqa: E402
from questline.score import score_cell  # noqa: E402


def git_commit() -> str | None:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    except Exception:
        return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lines", required=True)
    ap.add_argument("--batch", required=True)
    ap.add_argument("--worldbible", default="worldbible/worldbible_v1.json")
    ap.add_argument("--models", default="gpt,claude,gemini")
    ap.add_argument("--config", default=str(DEFAULT_CONFIG.relative_to(ROOT)),
                    help="모델 설정 파일 (기본은 동결값 configs/models.yaml - 확인 시험만 다른 파일을 쓴다)")
    ap.add_argument("--conditions", default=",".join(CONDITIONS))
    ap.add_argument("--reps", type=int, default=1)
    ap.add_argument("--first-rep", type=int, default=1,
                    help="첫 반복 번호 - seed 는 42 + 100×(r−1) + t 이므로 반복 번호가 seed 계열을 정한다(예비 측정은 2)")
    ap.add_argument("--line-ids", default="")
    ap.add_argument("--cost-cap", type=float)
    ap.add_argument("--probe-mix", default=",".join(f"{k}={v}" for k, v in PROBE_MIX.items()),
                    help="라인마다 함정 수 (예: custody=2,death=1). none 이면 보지 않는다")
    ap.add_argument("--dry-run", action="store_true", help="라인 형식 검사와 셀 수만 찍고 호출하지 않는다")
    args = ap.parse_args()

    cfg = load_config(ROOT / args.config)
    qcfg = cfg["questline"]
    cost_cap = args.cost_cap if args.cost_cap is not None else qcfg["cost_cap_usd"]
    wb = json.loads((ROOT / args.worldbible).read_text())
    ix = Index(wb)
    lines = load_lines(ROOT / args.lines)
    if args.line_ids:
        keep = set(args.line_ids.split(","))
        lines = [l for l in lines if l["id"] in keep]
    errs = validate_lines(lines, ix, probes_per_line=parse_probe_mix(args.probe_mix))
    if errs:
        sys.exit("라인 정의 오류:\n" + "\n".join(errs))
    models = args.models.split(",")
    conds = args.conditions.split(",")
    for c in conds:
        if c not in ALL_CONDITIONS:
            sys.exit(f"조건은 {ALL_CONDITIONS} 가운데 하나: {c}")
    reps = list(range(args.first_rep, args.first_rep + args.reps))
    n_cells = len(lines) * len(models) * len(conds) * args.reps
    print(f"라인 {len(lines)} × 모델 {len(models)} × 조건 {len(conds)} × 반복 {args.reps}(r={reps[0]}~{reps[-1]}) = {n_cells} 셀")
    if args.dry_run:
        return

    load_dotenv(ROOT / ".env")
    client = OpenRouterClient()
    specs = {m: ModelSpec.from_config(m, cfg) for m in models}
    out = ROOT / "runs" / "questline" / args.batch
    out.mkdir(parents=True, exist_ok=True)
    checks = {m: client.check_snapshot(s) for m, s in specs.items()}  # 다르면 SnapshotMismatch 로 멈춘다
    manifest = {"started_utc": utc_now(), "args": vars(args), "git_commit": git_commit(),
                "questline_config": qcfg, "sampling": cfg["sampling"], "snapshot_checks": checks}
    (out / f"manifest_{manifest['started_utc'].replace(':', '')}.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2))

    cells_path, scores_path, err_path = out / "cells.jsonl", out / "scores.jsonl", out / "errors.jsonl"
    done, spent = set(), 0.0
    if scores_path.exists():
        for l in scores_path.read_text().splitlines():
            r = json.loads(l)
            done.add((r["line_id"], r["model"], r["condition"], r["rep"]))
            spent += r["cost_usd"]
    sampling = dict(cfg["sampling"], max_tokens=qcfg["max_tokens"])

    with cells_path.open("a") as fc, scores_path.open("a") as fs:
        for rep in reps:
            for line in lines:
                for m in models:
                    for c in conds:
                        key = (line["id"], m, c, rep)
                        if key in done:
                            continue
                        if spent >= cost_cap:
                            print(f"비용 상한 ${cost_cap} 도달 (누계 ${spent:.3f}) - 멈춘다. 다시 실행하면 이어 간다")
                            return
                        try:
                            cell = run_cell(client, specs[m], wb, ix, line, c, rep, sampling, max_regen=qcfg["max_regen"])
                        except AdapterError as e:
                            with err_path.open("a") as fe:
                                fe.write(json.dumps({"key": key, "utc": utc_now(), "error": str(e)}, ensure_ascii=False) + "\n")
                            print(f"오류 {key}: {e}")
                            continue
                        row = score_cell(line, cell, ix)
                        spent += row["cost_usd"]
                        fc.write(json.dumps(cell, ensure_ascii=False) + "\n")
                        fs.write(json.dumps(row, ensure_ascii=False) + "\n")
                        fc.flush(), fs.flush()
                        print(f"r{rep} {line['id']} {m:6} {c} attempts={row['attempts']} "
                              f"completable={row['final_completable']} cost={row['cost_usd']:.4f} total={spent:.3f}", flush=True)


if __name__ == "__main__":
    main()
