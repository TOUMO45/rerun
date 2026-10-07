"""harness-v1.8 (T5, T3): which Debian package provides what a failed source build asked for, and which package names Debian has renamed.

PURE. No network, no model call, no filesystem. NOT sandbox-touching: it only decides WHICH apt package the existing, recorded apt step installs.

The evidence (records of the 21 held-out entries, now DEV-CONTAMINATED):
  - TEST-B #8 CSAILVision/gandissect: `src/checkdep_freetype2.c:1:10: fatal error: ft2build.h: No such file or directory`. `apt libfreetype6-dev` was
    proposed by the model on a losing branch and then barred as "already failed"; the run ended BLOCKED SYS_LIB_MISSING on the header it had a fix for.
  - TEST #13 seongjunyun/neo_gnns: `subprocess.CalledProcessError: Command '['which', 'g++']' returned non-zero exit status 1.` inside a pip build.
    The wrapper made it DEP_BUILD_FAILED, so the v1.1 compiler rule (SYS_LIB_MISSING only) never fired, and a candidate then compiled torch-scatter
    from source for 257 s.
  - TEST-B #3 alexlee-gk/video_prediction: the plan's `apt libgl1-mesa-glx` met `E: Package 'libgl1-mesa-glx' has no installation candidate`.

Every row is a fact about Debian package contents or names that I checked against the package names the Debian stable releases carry. A header or
tool that is NOT in the table is left to the repairer, exactly as before: the table never guesses.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# C/C++ header (as the compiler prints it, with its directory part) -> the Debian dev package that ships it.
HEADER_PACKAGES: dict[str, str] = {
    "ft2build.h": "libfreetype6-dev",
    "freetype/freetype.h": "libfreetype6-dev",
    "png.h": "libpng-dev",
    "pngconf.h": "libpng-dev",
    "jpeglib.h": "libjpeg-dev",
    "jconfig.h": "libjpeg-dev",
    "zlib.h": "zlib1g-dev",
    "bzlib.h": "libbz2-dev",
    "lzma.h": "liblzma-dev",
    "yaml.h": "libyaml-dev",
    "ffi.h": "libffi-dev",
    "ffitarget.h": "libffi-dev",
    "openssl/ssl.h": "libssl-dev",
    "openssl/err.h": "libssl-dev",
    "openssl/opensslv.h": "libssl-dev",
    "openssl/evp.h": "libssl-dev",
    "sqlite3.h": "libsqlite3-dev",
    "hdf5.h": "libhdf5-dev",
    "tiff.h": "libtiff-dev",
    "tiffio.h": "libtiff-dev",
    "sndfile.h": "libsndfile1-dev",
    "portaudio.h": "portaudio19-dev",
    "libxml/parser.h": "libxml2-dev",
    "libxml/tree.h": "libxml2-dev",
    "libxslt/xslt.h": "libxslt1-dev",
    "gmp.h": "libgmp-dev",
    "mpfr.h": "libmpfr-dev",
    "cairo.h": "libcairo2-dev",
    "glib.h": "libglib2.0-dev",
    "curl/curl.h": "libcurl4-openssl-dev",
    "zmq.h": "libzmq3-dev",
    "pcap.h": "libpcap-dev",
    "libusb.h": "libusb-1.0-0-dev",
    "mpi.h": "libopenmpi-dev",
    "cblas.h": "libopenblas-dev",
    "lapacke.h": "liblapacke-dev",
    "readline/readline.h": "libreadline-dev",
    "ncurses.h": "libncurses-dev",
    "curses.h": "libncurses-dev",
    "SDL2/SDL.h": "libsdl2-dev",
    "GL/gl.h": "libgl1-mesa-dev",
    "GL/glew.h": "libglew-dev",
    "GL/osmesa.h": "libosmesa6-dev",
    "X11/Xlib.h": "libx11-dev",
    "Eigen/Dense": "libeigen3-dev",
    "eigen3/Eigen/Dense": "libeigen3-dev",
    "boost/config.hpp": "libboost-dev",
    "opencv2/opencv.hpp": "libopencv-dev",
    "turbojpeg.h": "libturbojpeg0-dev",
}

# Tools a source build shells out to (`which X`, `command 'X' failed: No such file or directory`, `Cannot find command 'X'`): tool -> Debian package.
# g++, gcc, cc, c++ and make all come from build-essential, the package the v1.1 compiler rule has always installed.
TOOL_PACKAGES: dict[str, str] = {
    "g++": "build-essential",
    "gcc": "build-essential",
    "cc": "build-essential",
    "c++": "build-essential",
    "x86_64-linux-gnu-gcc": "build-essential",
    "make": "build-essential",
    "cmake": "cmake",
    "pkg-config": "pkg-config",
    "gfortran": "gfortran",
    "swig": "swig",
    "git": "git",
    "ninja": "ninja-build",
    "patch": "patch",
    "unzip": "unzip",
    "wget": "wget",
    "curl": "curl",
}
COMPILER_TOOLS = frozenset({"g++", "gcc", "cc", "c++", "x86_64-linux-gnu-gcc", "make"})

# Package names Debian has retired or renamed, and what the current releases carry instead. `libgl1-mesa-glx` was a transitional package
# that Debian 12 (bookworm) no longer ships; `libgl1` provides the same runtime library. Only renames I am sure of are listed.
DEBIAN_RENAMES: dict[str, str] = {
    "libgl1-mesa-glx": "libgl1",
    "libfreetype6-dev": "libfreetype-dev",
    "python-dev": "python3-dev",
    "python-pip": "python3-pip",
    "libpng12-dev": "libpng-dev",
    "libpng12-0": "libpng16-16",
    "libtiff5-dev": "libtiff-dev",
    "libtiff5": "libtiff6",
    "libssl1.0-dev": "libssl-dev",
    "libssl1.0.0": "libssl3",
}
# Removed from Debian with NO successor package (`libjasper-dev`): deliberately absent from DEBIAN_RENAMES, so `renamed_apt_package` returns None
# and the failure goes to the repairer instead of a substitution nobody can vouch for.

_HEADER_ERR = re.compile(r"fatal error:\s*([\w./+-]+\.(?:h|hpp)|[\w./+-]*Eigen/\w+):\s*No such file or directory")
_WHICH_ERR = re.compile(r"Command '\[(?:'which'|\"which\"), ?(?:'([\w+.-]+)'|\"([\w+.-]+)\")\]' returned non-zero exit status")
_CMD_FAILED = re.compile(r"(?:error: )?command '([\w+./-]+)' failed(?:: No such file or directory| with exit status 127)")
_UNABLE = re.compile(r"(?:unable|failed) to execute '?([\w+./-]+)'?:? ?(?:No such file or directory)?")
_NO_CMD = re.compile(r"Cannot find command '([\w+.-]+)'")
_NOT_FOUND = re.compile(r"(?:^|[\s:])([\w+.-]+): (?:command )?not found")
_NO_CANDIDATE = re.compile(r"E: Package '([\w+.:-]+)' has no installation candidate")
_UNABLE_LOCATE = re.compile(r"E: Unable to locate package ([\w+.:-]+)")


@dataclass(frozen=True)
class SystemNeed:
    """What a failed build or run needs from apt: `packages` to add, the log line that shows it (verbatim in the log), and the rule that fired."""

    packages: tuple[str, ...]
    evidence: str
    kind: str  # "compiler" | "header" | "tool"
    rule: str
    item: str  # the header or tool the log names


COMPILER_RULE = "missing_compiler_build_essential"  # the v1.1 / D-24 rule id, unchanged
HEADER_RULE = "missing_header_apt"
TOOL_RULE = "missing_tool_apt"


def _line_of(text: str, match: re.Match) -> str:
    start = text.rfind("\n", 0, match.start()) + 1
    end = text.find("\n", match.end())
    return text[start: end if end != -1 else len(text)].strip()[:500]  # capped (review, LOW): a megabyte line is not an evidence line


def _normalise_tool(name: str) -> str:
    name = name.rsplit("/", 1)[-1]
    return "gcc" if re.fullmatch(r"x86_64-linux-gnu-gcc(?:-\d+)?", name) else name


def header_package(header: str) -> str | None:
    """The Debian package for `header` as the compiler printed it (`ft2build.h`, `openssl/ssl.h`), by full name then by base name."""
    if header in HEADER_PACKAGES:
        return HEADER_PACKAGES[header]
    return HEADER_PACKAGES.get(header.rsplit("/", 1)[-1])


def need_in(log: str, last: bool = False) -> SystemNeed | None:
    """The thing a failed build's `log` says it could not find that apt can provide, or None. Looks for a missing C header, a missing compiler
    (the three ways pip, distutils and `which` report it) and a missing tool. `last=False` returns the FIRST one in reading order (the line a
    classifier already chose is one line, so its first match is the answer); `last=True` returns the LAST one (a whole build log: an earlier miss
    that a fallback recovered from is not the failure the run ended on).

    A header or tool the tables do not know returns None (never a guess)."""
    if not log:
        return None
    found: list[tuple[int, SystemNeed]] = []
    for m in _HEADER_ERR.finditer(log):
        pkg = header_package(m.group(1))
        if pkg:
            found.append((m.start(), SystemNeed((pkg,), _line_of(log, m), "header", HEADER_RULE, m.group(1))))
    for pat in (_WHICH_ERR, _CMD_FAILED, _UNABLE, _NO_CMD, _NOT_FOUND):
        for m in pat.finditer(log):
            tool = next((g for g in m.groups() if g), None)
            if not tool:
                continue
            tool = _normalise_tool(tool)
            pkg = TOOL_PACKAGES.get(tool)
            if not pkg:
                continue
            kind = "compiler" if tool in COMPILER_TOOLS else "tool"
            found.append((m.start(), SystemNeed((pkg,), _line_of(log, m), kind, COMPILER_RULE if kind == "compiler" else TOOL_RULE, tool)))
    if not found:
        return None
    return (max if last else min)(found, key=lambda t: t[0])[1]


def renamed_apt_package(log: str) -> tuple[str, str, str] | None:
    """(old, new, evidence line) when `log` says an apt package has no installation candidate and Debian has a known successor, else None.
    `new` is never empty: a package that was removed without a successor (`libjasper-dev`) returns None."""
    for pat in (_NO_CANDIDATE, _UNABLE_LOCATE):
        m = pat.search(log or "")
        if m:
            old = m.group(1)
            new = DEBIAN_RENAMES.get(old)
            if new and new != old:
                return old, new, _line_of(log, m)
    return None


def vcs_git_protocol_lines(text: str) -> list[str]:
    """Lines of a requirements text that use the retired `git://` protocol (GitHub switched off unauthenticated git:// on 2022-03-15)."""
    return [ln for ln in (text or "").splitlines() if re.search(r"(?:git\+)?git://github\.com/", ln)]


_GIT_PROTO = re.compile(r"(git\+)?git://github\.com/")


def rewrite_git_protocol(text: str) -> tuple[str, int]:
    """`text` with `git://github.com/` (and `git+git://github.com/`) rewritten to `https://github.com/` (`git+https://github.com/`), and the
    number of rewritten occurrences. Only github.com is touched: other hosts may still serve git://."""
    return _GIT_PROTO.subn(lambda m: f"{m.group(1) or ''}https://github.com/", text or "")
