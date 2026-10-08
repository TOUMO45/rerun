"""harness-v1.9 (D-72): a missing OUTPUT directory, told apart from missing data, and the one deterministic repair for it.

PURE. No network, no model, no sandbox.

TEST-C minmaxot finished its computation and then failed on `np.savetxt('output/objective_values_base1_0', ...)`: `output/` did not exist. It was classified
DATA_MISSING and the certificate asked for "the dataset the repository expects at output/objective_values_base1_0", which is wrong in kind; nine attempts found
no repair. A `FileNotFoundError` / `No such file or directory` is a missing output directory when the INNERMOST frame of the program's own code (the traceback is
read from the error upward; frames of the standard library and of site-packages are skipped) is a WRITE and its source line reads nothing: np.savetxt / save /
savez, torch.save, plt.savefig, DataFrame.to_csv / to_pickle / to_json, cv2.imwrite, `open(path, 'w' / 'a' / 'x' ...)`, `Path.write_text` / `write_bytes`.
The repair creates that directory (`mkdir -p -- <dir>`) as a RERUN-owned setup step and runs the documented command again, once per run, before any model call;
it never creates a file and never touches an input. A line that both writes and reads (`torch.save(train(load('data/x.npy')), 'out/m.pt')`) is not decided here:
it stays DATA_MISSING (review, M1: a missing dataset must reach data_prep and the dataset lookup).

Refused (the class stays, the repair is not made, the reason is logged): a path with no directory part (a file in the working directory cannot be missing its
directory), an absolute path or a home directory (also after a `cd`), a `..` component, a shell metacharacter. The command ends in `|| true` (as data_prep's
does): the step is kept in the run's setup commands, and a path component that is a file must not break every later execution.
"""
from __future__ import annotations

import posixpath
import re
import shlex
from dataclasses import dataclass

RULE = "output_dir"
_ERRNO = re.compile(r"(?:FileNotFoundError|IOError|OSError):\s*\[Errno 2\] No such file or directory:\s*['\"](?P<path>[^'\"]+)['\"]")
_WRITE_CALL = re.compile(
    r"\.(?:savetxt|save|savez|savez_compressed|savefig|to_csv|to_pickle|to_json|to_parquet|to_excel|to_hdf|imwrite|imsave|write_text|write_bytes|dump)\s*\("
    r"|\btorch\.save\s*\(|\bplt\.savefig\s*\(|\bimageio\.imwrite\s*\("
    r"|\bopen\s*\([^)]*(?:,\s*|mode\s*=\s*)['\"][rb+]*[wax][bt+]*['\"]"
)
# A read on the same source line: `np.load`, `torch.load`, `pd.read_*`, `pickle.load`, `json.load`, `imread`, `loadmat`, and `open(x)` with no mode or an r-mode.
_READ_CALL = re.compile(
    r"\b(?:np|numpy|torch|pickle|json|yaml|joblib|scipy|sio|h5py)\.(?:load|loads|loadtxt|genfromtxt|loadmat|safe_load)\s*\("
    r"|\.read_\w+\s*\(|\bread_(?:csv|table|pickle|json)\s*\(|\bimread\s*\(|\.read\s*\("
    r"|\bopen\s*\(\s*[^,()]+(?:\([^)]*\))?[^,()]*\)"
    r"|\bopen\s*\([^)]*,\s*['\"]r[bt+]*['\"]"
    r"|\b(?:load|read|fetch|parse|import)\w*\s*\("  # any helper that loads: `train(load_data('data/x.npy'))`
)
_FRAME_FILE = re.compile(r'^\s*File "(?P<file>[^"]*)", line \d+')
_LOOKBACK_LINES = 40
_UNSAFE = re.compile(r"[\s;&|`$<>()*?\[\]{}!\\\"']")


@dataclass(frozen=True)
class Miss:
    path: str          # the path the program could not write, as the error names it
    directory: str     # its directory part
    write_line: str    # the traceback source line that writes
    error_line: str    # the error line


def _library_frame(file: str) -> bool:
    f = file.replace("\\", "/")
    return f.startswith("<") or "site-packages" in f or "dist-packages" in f or "/lib/python" in f or "/Lib/" in f


def detect(text: str | None) -> Miss | None:
    """The LAST `[Errno 2] No such file or directory: '<path>'` in `text` whose innermost frame of the program's own code writes and reads nothing; else None."""
    lines = (text or "").splitlines()
    for i in range(len(lines) - 1, -1, -1):
        m = _ERRNO.search(lines[i])
        if not m:
            continue
        start = max(0, i - _LOOKBACK_LINES)
        frames = [(k, _FRAME_FILE.match(lines[k]).group("file")) for k in range(start, i) if _FRAME_FILE.match(lines[k])]
        for n, (k, file) in reversed(list(enumerate(frames))):
            if _library_frame(file):
                continue
            end = frames[n + 1][0] if n + 1 < len(frames) else i
            code = " ".join(ln.strip() for ln in lines[k + 1:end] if ln.strip())
            if _WRITE_CALL.search(code) and not _READ_CALL.search(code):
                path = m.group("path")
                return Miss(path, posixpath.dirname(path.replace("\\", "/")), code[:300], lines[i].strip()[:300])
            return None  # the innermost frame of the program's own code reads (or does something else): missing data, not a missing output directory
        return None  # no frame of the program's own code in the window
    return None


def _cd_prefix(command: str | None) -> str:
    """The directory a documented command first `cd`s into (`cd src && python x.py`), or ""."""
    m = re.match(r"^\s*cd\s+([^\s;&|]+)\s*&&", command or "")
    return m.group(1).strip("'\"").rstrip("/") if m else ""


def mkdir_command(miss: Miss, execute_command: str | None = None) -> tuple[str | None, str]:
    """(the setup command, the repository-relative directory) or (None, why the repair is not made)."""
    d = miss.directory
    if not d:
        return None, f"'{miss.path}' has no directory part: a missing directory is not what stops it"
    prefix = _cd_prefix(execute_command)
    joined = posixpath.join(prefix, d) if prefix else d
    if d.startswith(("/", "~")) or joined.startswith(("/", "~")) or re.match(r"^[A-Za-z]:", joined):
        return None, f"'{joined}' is not a path inside the repository (absolute or home directory): RERUN creates directories only inside the checkout"
    rel = posixpath.normpath(joined)
    if rel.startswith("..") or "/../" in f"/{rel}/" or _UNSAFE.search(rel) or rel in (".", ""):
        return None, f"'{rel}' leaves the repository or carries characters RERUN does not pass to a shell"
    return f"mkdir -p -- {shlex.quote(rel)} || true", rel
