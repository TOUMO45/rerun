"""Live verification of the in-sandbox download route (harness-v1.3.2): the real repo at its pinned commit, the real
sandbox.run_build_and_execute with the upload cap forced below the archive size, a real Nebius sandbox.

  backend/.venv/Scripts/python.exe scripts/verify_download_route.py <repo_url> <sha> <image> <out.json> [<overlay file>]

With <overlay file> (harness-v1.3.4, D-20): that repository file is patched locally (one marker line appended) before the upload, sent
as an overlay on the manifest-only archive, and the sandbox must (a) pass the integrity check and (b) show the marker in the file
(`OVERLAY_OK`). Without the overlay this exact case failed live with exit 97 (corpus-v2 entry 8, v1.3.3 smoke gate).
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


def main(repo_url: str, sha: str, image: str, out: Path, overlay_file: str | None = None) -> int:
    from app.config import get_settings
    from app.services import intake, sandbox, sandbox_limits, tree_integrity

    tmp = Path(tempfile.mkdtemp(prefix="rerun_dl_"))
    try:
        work = tmp / "repo"
        intake.clone_repo_at_commit(repo_url, work, sha)
        entries = tree_integrity.committed_entries(work, sha)
        files = {}
        for dp, _dn, fns in os.walk(work):
            cur = Path(dp)
            if ".git" in cur.relative_to(work).parts:
                continue
            for fn in fns:
                p = cur / fn
                if p.is_file() and not p.is_symlink():
                    files[p.relative_to(work).as_posix()] = p
        modes = {k: v[0] for k, v in entries.items()}
        overlay_paths = frozenset()
        check = "cat /tmp/rerun_fetch_route; echo; test ! -e .git && echo NO_DOT_GIT; ls -A | wc -l; test ! -e .rerun_upload_v1 && echo NO_RERUN_DIR"
        if overlay_file:
            target = work / overlay_file
            target.write_bytes(target.read_bytes() + b"\n# RERUN_OVERLAY_MARK\n")  # the gate-approved patch, simulated
            overlay_paths = frozenset({overlay_file})
            check += f"; grep -c RERUN_OVERLAY_MARK {overlay_file} | grep -qx 1 && echo OVERLAY_OK"
        source = sandbox_limits.DownloadSource.from_repo_url(repo_url, sha)
        sandbox.UPLOAD_CAP_BYTES = 1  # force the download route
        s = get_settings()
        rec = {"repo_url": repo_url, "sha": sha, "image": image, "files": len(files), "overlay_file": overlay_file,
               "started_at": datetime.now(timezone.utc).isoformat()}
        try:
            r = sandbox.run_build_and_execute(
                api_key=s.nebius_api_key, project_id=s.nebius_project_id, base_image=image, install_commands=[],
                execute_command=check,
                wall_clock_seconds=900, upload_files=files, file_modes=modes, download_source=source, overlay_paths=overlay_paths)
            ok = r.succeeded and (not overlay_file or "OVERLAY_OK" in r.final.stdout)
            rec.update(ok=ok, stdout=r.final.stdout.strip()[-800:], stderr=r.final.stderr.strip()[-400:],
                       cost_usd=r.total_cost_usd, extract_seconds=r.extract_seconds, run_id=str(r.sandbox_id))
        except Exception as exc:
            rec.update(ok=False, error=f"{type(exc).__name__}: {str(exc)[:1500]}", stderr=getattr(exc, "stderr", ""))
        print(json.dumps(rec, indent=1))
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(rec, indent=2) + "\n", encoding="utf-8", newline="\n")
        return 0 if rec["ok"] else 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1], sys.argv[2], sys.argv[3], Path(sys.argv[4]), sys.argv[5] if len(sys.argv) > 5 else None))
