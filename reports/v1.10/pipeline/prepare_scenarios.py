"""harness-v1.10 pass, task 1: the baseline of each base repository on its kept environment image, run once with the UNPATCHED documented command (a real sandbox run each).

    backend/.venv/Scripts/python.exe reports/v1.10/pipeline/prepare_scenarios.py --worktree .claude/worktrees/v110-harness-v1.9.0 [--go]

It writes `scenarios.json`: per base the image, the documented command, the observed baseline (exit code, smoke outcome, the output tails, the classifier's reading) and the
POPULATION it puts the base in:

  A  the unpatched run FAILS on this image (exit != 0, or the smoke launcher says it failed): the loop is in its repair state, and the failure being repaired is the failure
     observed here (`<class>: <evidence>`, as the orchestrator hands it to the adjudicator);
  B  the unpatched run PASSES on this image (the deterministic rules already fixed the recorded failure): a planted code patch has no failure to repair; the failure handed to
     the adjudicator is the base's recorded last error-chain link, and the base is reported separately.

The images are the kept images of the bases' committed records (reports/v1.10/pipeline/PROTOCOL.md says which and why). Cost: one smoke run per base.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import common  # noqa: E402

ROOT = common.ROOT

# base -> (record whose kept image is used, attempt number, image id prefix to pick, why). Full image ids are read from the record.
IMAGES = {
    "latent_ode": ("runs/corpus_v2_batch/harness-v1.7.1/dev/15_YuliaRubanova__latent_ode.json", 1, 1, "the adopted candidate's image (the dependency fix: `dataclasses` removed); tree unpatched"),
    "SimplE": ("runs/corpus_v2_batch/harness-v1.7.1/dev/12_Mehran-k__SimplE.json", 0, 0, "the image of the first time-machine run (era lock), before the removed-API rule"),
    "FeatureScatter": ("runs/corpus_v2_batch/harness-v1.7.1/dev/17_Haichao-Zhang__FeatureScatter.json", 0, 0, "the image after the removed-API rule"),
    "M-FAC": ("runs/corpus_v2_batch/harness-v1.5.2/dev/14_IST-DASLab__M-FAC.json", 0, 0, "the image of the first time-machine run (CPU shim installed), the one the model's candidates branched from"),
    "patchSmoothing": ("runs/corpus_v2_batch/harness-v1.5-final/test/10_alevine0__patchSmoothing.json", 0, 0, "the image before the CPU shim (dependency fixed, CUDA error)"),
    "L2D": ("runs/corpus_v3_batch/harness-v1.7.2/treatment/04_zcajiayin__L2D.json", 0, 0, "the image before the CPU shim (dependency fixed, CUDA error)"),
    "MIR": ("runs/corpus_v4_batch/harness-v1.8.0/treatment/08_optimass__Maximally_Interfered_Retrieval.json", 0, 0, "the image after the apt-archive rule"),
}


def pick_image(rel: str, attempt: int, occurrence: int) -> str:
    """The image id of the `occurrence`-th (0-based) attempt record numbered `attempt` that carries one; for latent_ode the ADOPTED candidate (chosen true)."""
    rec = json.loads((ROOT / rel).read_text(encoding="utf-8"))
    atts = [a for a in rec["result"]["attempts"] if a.get("attempt_number") == attempt and (a.get("execution") or {}).get("image")]
    if "latent_ode" in rel:
        atts = [a for a in atts if a.get("chosen") is True]
    return atts[occurrence if "latent_ode" not in rel else 0]["execution"]["image"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--worktree", required=True)
    ap.add_argument("--tag", default="harness-v1.9.0")
    ap.add_argument("--out", default=str(HERE / "scenarios.json"))
    ap.add_argument("--go", action="store_true")
    args = ap.parse_args()
    h = common.load_harness(Path(args.worktree), args.tag)
    bases = {b["name"]: b for b in json.loads((ROOT / "reports/v1.9/planted/bases.json").read_text(encoding="utf-8"))["bases"]}
    scenarios = {}
    for name, (rel, attempt, occ, why) in IMAGES.items():
        image = pick_image(rel, attempt, occ)
        rec = json.loads((ROOT / rel).read_text(encoding="utf-8"))
        last = (rec["result"].get("error_chain") or [{}])[-1]
        scenarios[name] = {"base": name, "record": rel, "image": image, "image_why": why, "command": bases[name]["command"],
                           "recorded_failure": f"{last.get('class')}: {last.get('error')}"[:600]}
    print(f"preflight ok at {h.tag} {h.head[:8]}; {len(scenarios)} bases; each baseline is one smoke run (about $0.07)")
    if not args.go:
        for s in scenarios.values():
            print(f"  {s['base']:15} image {s['image'][:8]}  {s['command'][:70]}")
        return 0
    spent = 0.0
    for name, s in scenarios.items():
        step = common.run_on_image(h, s["image"], s["command"], None)
        spent += step.cost_usd
        res = common.sandbox_result(h, step)
        execution = h.smoke_exec.execution_record(common.SMOKE_SECONDS, step.exit_code, step.stdout, step.stderr)
        passed = bool(res.succeeded)
        cls = None
        if step.exit_code != 0:
            c = h.classifier.classify(step.exit_code, step.stderr, step.stdout)
            cls = {"code": c.code, "evidence": (c.evidence or "")[:400]}
        s.update(baseline={"exit_code": step.exit_code, "smoke": execution, "passed": passed, "timed_out": step.timed_out, "seconds": round(step.elapsed_seconds, 2),
                           "cost_usd": round(step.cost_usd, 6), "exit_zero_check": h.exit_zero_check.finding_of(res), "classification": cls, **common.tails(step)},
                 population="B" if passed else "A",
                 failure=(f"{cls['code']}: {cls['evidence']}" if cls else s["recorded_failure"]),
                 failure_source="observed on the image" if cls else "the base's recorded last error-chain link (the image's unpatched run passes)")
        print(f"  {name:15} exit {step.exit_code:>3} {execution['outcome']:>14} -> population {s['population']}  {s['failure'][:90]}")
    Path(args.out).write_text(json.dumps({"harness_tag": h.tag, "harness_head": h.head, "baseline_spend_usd": round(spent, 6), "scenarios": scenarios}, indent=1) + "\n",
                              encoding="utf-8", newline="\n")
    print(f"baseline spend ${spent:.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
