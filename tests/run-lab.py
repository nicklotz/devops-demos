#!/usr/bin/env python3
"""Run lab files the way a student would, and check the results.

Usage: tests/run-lab.py [--catchup] [--log-dir DIR] labs/01-....md [labs/02-....md ...]

Conventions in the lab markdown:
  ```bash blocks           run in order in ONE persistent bash session (cd and export carry over)
  <!-- file: PATH -->      before a fenced block: write the block's content to PATH
  <!-- test ... -->        hidden check: bash, run in a subshell with `set -e` and tests/lib.sh
  <!-- ui: ACTION ARGS --> a Harness UI step: runs ui_ACTION from tests/lib.sh (the API equivalent)
  <!-- skip -->            do not run the next block
  <!-- expect-fail -->     the next bash block must fail
  <!-- catchup: skip -->   skip the next block or directive when replaying (--catchup)
  <!-- catchup: skip-start --> ... <!-- catchup: skip-end -->  skip a range when replaying
  <!-- runner: stop -->    ignore the rest of the file
"""

import argparse
import os
import re
import shlex
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
LIB = HERE / "lib.sh"
FENCE = re.compile(r"^(\s*)(`{3,})\s*([\w+-]*)\s*$")
BLOCK_TIMEOUT = 1800


def parse(path):
    """Turn a lab file into a list of actions."""
    lines = Path(path).read_text().splitlines()
    actions, pending, i = [], {}, 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        lineno = i + 1
        if stripped.startswith("<!--"):
            if stripped.startswith("<!-- test"):
                body = []
                rest = stripped[len("<!-- test"):]
                if rest.strip().endswith("-->"):
                    body.append(rest.strip()[:-3])
                else:
                    if rest.strip():
                        body.append(rest)
                    i += 1
                    while i < len(lines) and not lines[i].strip().endswith("-->"):
                        body.append(lines[i])
                        i += 1
                    last = lines[i].strip()[:-3] if i < len(lines) else ""
                    if last.strip():
                        body.append(last)
                actions.append({"kind": "test", "code": "\n".join(body), "line": lineno, **pending})
                pending = {}
            else:
                m = re.match(r"<!--\s*(.*?)\s*-->$", stripped)
                directive = m.group(1) if m else ""
                if directive.startswith("file:"):
                    pending["file"] = directive[5:].strip()
                elif directive == "skip":
                    pending["skip"] = True
                elif directive == "expect-fail":
                    pending["expect_fail"] = True
                elif directive == "catchup: skip":
                    pending["catchup_skip"] = True
                elif directive == "catchup: skip-start":
                    actions.append({"kind": "catchup-start", "line": lineno})
                elif directive == "catchup: skip-end":
                    actions.append({"kind": "catchup-end", "line": lineno})
                elif directive == "runner: stop":
                    break
                elif directive.startswith("ui:"):
                    actions.append({"kind": "ui", "args": shlex.split(directive[3:].strip()),
                                    "line": lineno, **pending})
                    pending = {}
            i += 1
            continue
        m = FENCE.match(line)
        if m:
            indent, fence, lang = m.group(1), m.group(2), m.group(3)
            body = []
            i += 1
            while i < len(lines):
                close = FENCE.match(lines[i])
                if close and close.group(2) == fence and close.group(3) == "":
                    break
                body.append(lines[i][len(indent):] if lines[i].startswith(indent) else lines[i].lstrip())
                i += 1
            content = "\n".join(body) + "\n"
            if "file" in pending:
                actions.append({"kind": "file", "path": pending.pop("file"), "content": content,
                                "line": lineno, **pending})
            elif lang == "bash":
                actions.append({"kind": "bash", "code": content, "line": lineno, **pending})
            pending = {}
        i += 1
    return actions


class Shell:
    """One long-running bash process that behaves like the student's terminal."""

    def __init__(self, log):
        self.log = log
        self.tmp = Path(tempfile.mkdtemp(prefix="runlab-"))
        self.count = 0
        env = dict(os.environ, DEBIAN_FRONTEND="noninteractive", GIT_TERMINAL_PROMPT="0",
                   TERM="dumb", NO_COLOR="1", PAGER="cat", GIT_PAGER="cat", SYSTEMD_PAGER="")
        self.proc = subprocess.Popen(["bash", "--norc", "--noprofile"], stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                     bufsize=1, cwd=Path.home(), env=env)

    def send(self, text):
        self.proc.stdin.write(text)
        self.proc.stdin.flush()

    def run(self, script, timeout=BLOCK_TIMEOUT, subshell=False):
        """Run a script. Returns (ok, output). ok is False if any command failed."""
        self.count += 1
        path = self.tmp / f"block-{self.count}.sh"
        path.write_text(script)
        marker = f"__RUNLAB_{self.count}_DONE__"
        if subshell:
            cmd = (f"( set -e; source {LIB}; source {path} ) < /dev/null; "
                   f"echo \"{marker} $?\"\n")
        else:
            cmd = (f"__rl=0; trap 'echo \"__RUNLAB_ERR__ exit $? :: $BASH_COMMAND\"; __rl=1' ERR; "
                   f"source {path} < /dev/null; trap - ERR; echo \"{marker} $__rl\"\n")
        self.send(cmd)
        return self._collect(marker, timeout)

    def raw(self, line, timeout=120):
        """Send a line as typed (used for `newgrp docker`, which starts a new shell on stdin)."""
        self.count += 1
        marker = f"__RUNLAB_{self.count}_DONE__"
        self.send(line + "\n")
        self.send(f"echo \"{marker} 0\"\n")
        return self._collect(marker, timeout)

    def _collect(self, marker, timeout):
        out, start, failed = [], time.time(), False
        while True:
            line = self.proc.stdout.readline()
            if not line:
                return False, out + ["(shell exited)"]
            line = line.rstrip("\n")
            if marker in line:
                # Output without a final line break (for example `cat` of a file that does not end
                # with one) puts the marker at the end of the last output line.
                before, _, status = line.partition(marker)
                if before:
                    out.append(before)
                    self.log(f"    {before}")
                failed = status.split() != ["0"]
                break
            out.append(line)
            self.log(f"    {line}")
            if time.time() - start > timeout:
                return False, out + [f"(timed out after {timeout}s)"]
        return not failed, out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("labs", nargs="+")
    ap.add_argument("--catchup", action="store_true", help="replay mode: honour catchup: skip markers")
    ap.add_argument("--log-dir", default=str(Path.home() / "lab-runs"))
    ap.add_argument("--from", dest="from_line", type=int, default=0,
                    help="start the first lab at this line (for re-running after a fix)")
    ap.add_argument("--cwd", default=None, help="working folder of the shell when starting with --from")
    args = ap.parse_args()

    Path(args.log_dir).mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    logfile = open(Path(args.log_dir) / f"run-{stamp}.log", "a", buffering=1)

    def log(msg):
        print(msg, flush=True)
        logfile.write(msg + "\n")

    shell = Shell(log)
    if args.cwd:
        shell.run(f"cd {shlex.quote(os.path.expanduser(args.cwd))}\n")
    started = time.time()
    results = []
    for index, lab in enumerate(args.labs):
        name = Path(lab).name
        start_line = args.from_line if index == 0 else 0
        log(f"\n===== {name} =====")
        lab_start = time.time()
        in_catchup_skip = False
        for a in parse(lab):
            where = f"{name}:{a['line']}"
            if a["line"] < start_line:
                continue
            if a["kind"] == "catchup-start":
                in_catchup_skip = args.catchup
                continue
            if a["kind"] == "catchup-end":
                in_catchup_skip = False
                continue
            if a.get("skip") or (args.catchup and (a.get("catchup_skip") or in_catchup_skip)):
                log(f"--- {where} {a['kind']} (skipped)")
                continue
            t0 = time.time()
            if a["kind"] == "file":
                target = Path(os.path.expanduser(a["path"]))
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(a["content"])
                log(f"--- {where} file {a['path']} ({len(a['content'].splitlines())} lines)")
                continue
            if a["kind"] == "bash":
                log(f"--- {where} bash" + (" (expect failure)" if a.get("expect_fail") else ""))
                for cmdline in a["code"].strip().splitlines()[:3]:
                    log(f"  $ {cmdline}")
                parts = re.split(r"^\s*(newgrp \S+)\s*$", a["code"], flags=re.M)
                ok, out = True, []
                for idx, part in enumerate(parts):
                    if idx % 2 == 1:
                        ok_part, out_part = shell.raw(part.strip())
                    elif part.strip():
                        ok_part, out_part = shell.run(part)
                    else:
                        continue
                    ok, out = ok and ok_part, out + out_part
                if a.get("expect_fail"):
                    ok = not ok
            elif a["kind"] == "test":
                log(f"--- {where} test")
                ok, out = shell.run(a["code"], subshell=True)
            elif a["kind"] == "ui":
                log(f"--- {where} ui: {' '.join(a['args'])}")
                func = "ui_" + a["args"][0]
                ok, out = shell.run(f"{func} " + " ".join(shlex.quote(x) for x in a["args"][1:]) + "\n",
                                    subshell=True)
            log(f"    [{'ok' if ok else 'FAILED'} in {time.time() - t0:.0f}s]")
            if not ok:
                log(f"\nFAILED at {where} ({a['kind']})")
                results.append((name, "FAILED", time.time() - lab_start))
                summarize(log, results, started)
                sys.exit(1)
        results.append((name, "passed", time.time() - lab_start))
        log(f"===== {name} passed in {(time.time() - lab_start) / 60:.1f} min =====")
    summarize(log, results, started)


def summarize(log, results, started):
    log("\nSummary")
    for name, status, secs in results:
        log(f"  {name:40s} {status:7s} {secs / 60:5.1f} min")
    log(f"  total {(time.time() - started) / 60:.1f} min")


if __name__ == "__main__":
    main()
