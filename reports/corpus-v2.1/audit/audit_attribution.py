"""Read-only attribution audit of a finished CONTROL arm (corpus-v2.1). Modifies nothing under runs/ or the sealed tag.

For every non-PASS record it finds out whether the failing module is declared ANYWHERE in the repository at the pinned commit
(requirements*.txt in any directory, setup.py, setup.cfg, pyproject.toml, environment.y[a]ml, Pipfile, conda files, Dockerfile*,
and pip/conda install lines in README/docs), records file + line as evidence, and proposes a secondary label:

  REPO_UNDECLARED       the module is declared nowhere: a genuine undeclared dependency
  DECLARED_NOT_PARSED   declared somewhere the harness did not act on: a HARNESS GAP (evidence kind says where)
  PLATFORM_REQUIRED     needs a GPU / Docker / hardware the sandbox does not have
  ENV_ROT               unresolvable or drifted historical pins (a pin that no longer exists, an API that newer libraries removed)
  INFRA                 an external-service failure (NOT_MEASURED)

It reports the gate count twice: (a) the pre-registered rule (a REPO-attributed link in the error chain of a non-PASS record),
(b) the audit (REPO_UNDECLARED only).

  backend/.venv/Scripts/python.exe reports/corpus-v2.1/audit/audit_attribution.py runs/corpus_v2_batch/harness-v1.3.2/control
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "backend"))
OUT = Path(__file__).resolve().parent

# import name -> extra distribution names (on top of app.services.import_names)
ALIASES = {
    "sklearn": ["scikit-learn", "sklearn"], "cv2": ["opencv-python", "opencv-python-headless", "opencv-contrib-python", "opencv"],
    "PIL": ["pillow", "pil"], "yaml": ["pyyaml"], "skimage": ["scikit-image"], "tensorflow": ["tensorflow", "tensorflow-gpu", "tensorflow-cpu"],
    "torch_sparse": ["torch-sparse"], "torch_geometric": ["torch-geometric"], "torch_scatter": ["torch-scatter"],
    "bs4": ["beautifulsoup4"], "tqdm": ["tqdm"], "matplotlib": ["matplotlib"], "scipy": ["scipy"], "chainer": ["chainer"],
    "tabulate": ["tabulate"],
}
MANIFEST = re.compile(r"(^|/)(requirements[^/]*\.(txt|in)|constraints[^/]*\.txt|setup\.py|setup\.cfg|pyproject\.toml|"
                      r"environment[^/]*\.ya?ml|conda[^/]*\.ya?ml|[^/]*conda[^/]*\.txt|Pipfile|Pipfile\.lock|tox\.ini|"
                      r"Dockerfile[^/]*|[^/]*\.dockerfile|docker-compose[^/]*\.ya?ml|Makefile|[^/]*\.sh)$", re.I)
DOCS = re.compile(r"(^|/)(README[^/]*|INSTALL[^/]*|CONTRIBUTING[^/]*|docs?/.*\.(md|rst|txt)|[^/]*\.(md|rst))$", re.I)
INSTALL_LINE = re.compile(r"(pip3?\s+install|conda\s+install|mamba\s+install|python3?\s+-m\s+pip\s+install|poetry\s+add|pipenv\s+install)", re.I)
MAX_BYTES = 600_000


def norm(s: str) -> str:
    return re.sub(r"[-_.]+", "-", s.lower())


def candidates(module: str) -> list[str]:
    from app.services.import_names import dist_for_import

    top = module.split(".")[0]
    names = {norm(top), norm(dist_for_import(top))} | {norm(a) for a in ALIASES.get(top, [])}
    return sorted(names)


def git(repo: Path, *args: str, check: bool = True) -> str:
    p = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, encoding="utf-8", errors="replace")
    if check and p.returncode != 0:
        raise RuntimeError(p.stderr.strip()[:300])
    return p.stdout


def fetch_files(url: str, sha: str, tmp: Path) -> tuple[Path, list[str]]:
    repo = Path(tempfile.mkdtemp(prefix="r_", dir=tmp))  # a fresh, empty directory per repo
    subprocess.run(["git", "clone", "-q", "--filter=blob:none", "--no-checkout", url, str(repo)], check=True, capture_output=True, timeout=600)
    files = git(repo, "ls-tree", "-r", "--name-only", sha).splitlines()
    return repo, files


def search(repo: Path, sha: str, files: list[str], names: list[str]) -> list[dict]:
    pats = [re.compile(r"(?<![a-z0-9-])" + re.escape(n) + r"(?![a-z0-9-])") for n in names]
    hits = []
    for path in files:
        is_manifest, is_docs = bool(MANIFEST.search(path)), bool(DOCS.search(path))
        if not (is_manifest or is_docs) or path.startswith(("third_party/", "vendor/", "node_modules/")):
            continue
        try:
            blob = subprocess.run(["git", "-C", str(repo), "show", f"{sha}:{path}"], capture_output=True, timeout=120).stdout
        except subprocess.TimeoutExpired:
            continue
        if len(blob) > MAX_BYTES or b"\0" in blob[:2000]:
            continue
        for i, line in enumerate(blob.decode("utf-8", "replace").splitlines(), start=1):
            low = norm(line)
            if not any(p.search(low) for p in pats):
                continue
            base = path.rsplit("/", 1)[-1].lower()
            if is_docs and not is_manifest:
                # An install line is a declaration; a prose mention ("requires TensorFlow") is only reported (docs_mention).
                kind = "docs_install_line" if INSTALL_LINE.search(line) else "docs_mention"
            elif base.startswith("dockerfile") or base.endswith(".dockerfile") or base.startswith("docker-compose"):
                kind = "dockerfile"
            elif base.endswith((".sh", "makefile", "tox.ini")) or base == "makefile":
                if not INSTALL_LINE.search(line):
                    continue
                kind = "script_install_line"
            else:
                kind = "manifest"
            hits.append({"file": path, "line": i, "text": line.strip()[:220], "kind": kind,
                         "commented": line.lstrip().startswith("#")})
    return hits


def module_of(error: str) -> str | None:
    m = re.search(r"No module named ['\"]?([\w.\-]+)['\"]?", error or "")
    return m.group(1) if m else None


PLATFORM = re.compile(r"docker: not found|No GPU found|CUDA|cuda|nvidia-smi|no NVIDIA|Torch not compiled|--cuda|GPU", re.I)


def label_non_dep(rec: dict, error: str) -> tuple[str, str, bool]:
    """(label, rationale, judgment_call) for a record that is not a DEP_MISSING."""
    verdict = rec["result"]["verdict"]
    reason = rec["result"].get("indeterminate_reason") or ""
    if verdict == "INFRA_ERROR" or reason.startswith("INFRA_ERROR"):
        return "INFRA", "external-service failure; NOT_MEASURED", False
    if reason.startswith("RUNNER_SETUP_FAILED"):
        if re.search(r"ResolutionImpossible|Could not find a version|No matching distribution", error):
            return "ENV_ROT", "the runner's torch install could not resolve the repo's historical pins on this Python", False
        return "ENV_ROT", "runner setup failed; see error", True
    if PLATFORM.search(error):
        return "PLATFORM_REQUIRED", "the command needs a GPU / Docker the sandbox does not provide", False
    if re.search(r"cannot import name .* from 'torch", error):
        return "ENV_ROT", "an API removed from newer torch (the repo pins no torch; the runner installs the newest): unpinned drift", True
    return "UNLABELED", "needs a manual read", True


def main(control_dir: str) -> int:
    d = ROOT / control_dir
    rows = []
    tmpdir = Path(tempfile.mkdtemp(prefix="rerun_audit_"))
    try:
        for f in sorted(d.glob("[0-9][0-9]_*.json")):
            rec = json.loads(f.read_text(encoding="utf-8"))
            res, entry = rec["result"], rec["corpus_entry"]
            verdict = res["verdict"]
            chain = res.get("error_chain") or []
            first_repo = res.get("first_repo_error")
            error = (chain[-1]["error"] if chain else "") or res.get("indeterminate_reason") or ""
            row = {"id": rec["batch"]["entry_id"], "name": entry["name"], "repo_url": entry["repo_url"], "commit": entry["commit_sha"],
                   "verdict": verdict, "taxonomy_code": res.get("taxonomy_code"), "reason_code": res.get("reason_code"),
                   "error": error[:300], "chain": [(l["class"], l["attribution"], l.get("phase")) for l in chain],
                   "registered_repo_attributed": verdict not in ("RUNS_CLEAN",) and first_repo is not None,
                   "harness_declared_dependencies": rec["intake"].get("declared_dependencies"),
                   "harness_dependency_files": rec["intake"].get("dependency_files"),
                   "spent_usd": round(rec["cost_guard"]["spent_usd"], 4)}
            if verdict == "RUNS_CLEAN":
                row.update(label="PASS", rationale="ran clean", judgment=False, evidence=[])
            elif (res.get("taxonomy_code") == "DEP_MISSING" or "No module named" in error) and not str(res.get("indeterminate_reason", "")).startswith(("RUNNER_SETUP", "INFRA")):
                module = module_of(error)
                names = candidates(module) if module else []
                row.update(module=module, candidate_names=names)
                try:
                    repo, files = fetch_files(entry["repo_url"], entry["commit_sha"], tmpdir)
                    hits = search(repo, entry["commit_sha"], files, names)
                except Exception as exc:  # recorded, never hidden
                    row.update(label="UNLABELED", rationale=f"audit could not read the repo: {type(exc).__name__}: {str(exc)[:200]}",
                               judgment=True, evidence=[])
                    rows.append(row)
                    print(row["id"], row["name"], "ERROR", row["rationale"], flush=True)
                    continue
                live = [h for h in hits if not h["commented"] and h["kind"] != "docs_mention"]
                row["readme_mentions"] = [h for h in hits if h["kind"] == "docs_mention" and not h["commented"]][:5]
                tops = {f.split("/")[0] for f in files} | {f[:-3] for f in files if f.endswith(".py") and "/" not in f}
                row["internal_module"] = bool(module) and module.split(".")[0] in tops
                row["evidence"] = hits
                if live:
                    kinds = sorted({h["kind"] for h in live})
                    row.update(label="DECLARED_NOT_PARSED", judgment=False,
                               rationale=f"'{module}' is declared in the repo ({', '.join(kinds)}); the harness did not act on it")
                else:
                    row.update(label="REPO_UNDECLARED", judgment=row["internal_module"],
                               rationale=f"'{module}' (as {', '.join(names)}) is declared in no manifest, Dockerfile, or install line"
                                         + (f"; the README mentions it in prose ({len(row['readme_mentions'])} line(s))" if row["readme_mentions"] else "")
                                         + ("; it is the repo's OWN module (a compiled extension / build step), not a package" if row["internal_module"] else ""))
            else:
                label, why, judgment = label_non_dep(rec, error)
                row.update(label=label, rationale=why, judgment=judgment, evidence=[])
            rows.append(row)
            print(row["id"], row["name"], row["label"], "|", row["rationale"][:110], flush=True)
    finally:
        shutil.rmtree(tmpdir, onerror=lambda f, p_, e: (os.chmod(p_, 0o700), f(p_)))

    non_pass = [r for r in rows if r["verdict"] != "RUNS_CLEAN"]
    a = sum(1 for r in non_pass if r["registered_repo_attributed"])
    b = sum(1 for r in non_pass if r["label"] == "REPO_UNDECLARED")
    b_strict = sum(1 for r in non_pass if r["label"] == "REPO_UNDECLARED" and not r.get("internal_module"))
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["label"]] = counts.get(r["label"], 0) + 1
    out = {"control_dir": control_dir, "entries": len(rows), "labels": counts,
           "gate_registered_rule": a, "gate_audit": b, "gate_audit_excluding_internal_modules": b_strict, "gate_threshold": 8, "gate_registered_passes": a >= 8, "gate_audit_passes": b >= 8,
           "declared_not_parsed": [r["id"] for r in rows if r["label"] == "DECLARED_NOT_PARSED"], "rows": rows}
    (OUT / "audit_attribution.json").write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8", newline="\n")
    lines = ["| # | entry | verdict | first error | registered | audit label | evidence / rationale |", "|--|--|--|--|--|--|--|"]
    for r in rows:
        ev = "; ".join(f"`{h['file']}:{h['line']}` {h['text'][:60]}" for h in r.get("evidence", [])[:2] if not h["commented"] and h["kind"] != "docs_mention") or r["rationale"]
        lines.append(f"| {r['id']} | {r['name']} | {r['verdict']} | {r['error'][:70].replace('|', '/')} | "
                     f"{'REPO' if r['registered_repo_attributed'] else '-'} | {r['label']}{' (judgment)' if r['judgment'] else ''} | {ev.replace('|', '/')} |")
    lines += ["", f"**Gate (>= 8 REPO-attributed non-PASS):** (a) pre-registered rule = **{a}**; (b) audit (REPO_UNDECLARED only) = **{b}** ({b_strict} if the repo's own compiled module of entry 19 is excluded).", f"Labels: {counts}"]
    (OUT / "audit_attribution.md").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({k: v for k, v in out.items() if k != "rows"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1]))
