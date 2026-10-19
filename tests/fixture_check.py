#!/usr/bin/env python3
"""Syntax-check every catalog command and execute the examples that carry a
"test" block inside a throw-away fixture directory.

Linux only (needs bash). Nothing outside the fixture is written:
- each example gets a fresh fixture under one tempfile.mkdtemp(prefix="lcg-fixture-") directory;
- HOME points inside that directory, stdin is /dev/null, every run has a timeout;
- the catalog tests (test_catalog.py) forbid sudo, network, package, service and
  device tools, and absolute write targets, in executed examples;
- at the end exactly that one temporary directory is removed.

Usage: python3 tests/fixture_check.py [--only <command-id>] [-v]
"""
import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
PLACEHOLDER_RE = re.compile(r"<([a-z][a-z0-9_.-]*)>")
PREFIX = "lcg-fixture-"
TIMEOUT = 20

BASH_BUILTINS = {
    "cd", "echo", "printf", "export", "alias", "history", "type", "jobs", "fg", "bg", "set", "test",
    "read", "help", "kill", "wait", "true", "false", "umask", "source", ".", "exit", "command", "{",
    "}", "for", "while", "if", "then", "do", "done", "fi", "[", "[[", "time", "!", "unset", "hash",
}

HELLO_C = """#include <stdio.h>

int main(void)
{
    printf("Hello, embedded world\\n");
    return 0;
}
"""

MAKEFILE = "hello: hello.c\n\t$(CC) -Wall -o hello hello.c\n\nclean:\n\trm -f hello\n"

NOTES = "apple\nbanana\napple\nTODO: fix the driver probe\ncherry\nerror: something failed\nbanana\n"

APP_LOG = (
    "2024-05-01 10:00:01 INFO start\n"
    "2024-05-01 10:00:02 ERROR probe failed\n"
    "2024-05-01 10:00:03 INFO retry\n"
    "2024-05-01 10:00:04 ERROR timeout\n"
    "2024-05-01 10:00:05 INFO done\n"
)

CSV = "name,role,cores\nalice,dev,4\nbob,ops,8\ncarol,dev,2\n"


def build_fixture(path: Path) -> None:
    path.mkdir()
    (path / "notes.txt").write_text(NOTES)
    (path / "file with spaces.txt").write_text("hello\n")
    (path / "logs").mkdir()
    (path / "logs" / "app.log").write_text(APP_LOG)
    (path / "data.csv").write_text(CSV)
    (path / "src").mkdir()
    (path / "src" / "hello.c").write_text(HELLO_C)
    (path / "src" / "Makefile").write_text(MAKEFILE)
    (path / "big").mkdir()
    with open(path / "big" / "data.bin", "wb") as fh:
        for _ in range(32):
            fh.write(b"\0" * 65536)  # 2 MiB of real (non-sparse) data
        fh.flush()
        os.fsync(fh.fileno())
    (path / "home").mkdir()


def load_entries():
    categories = json.loads((DATA / "categories.json").read_text(encoding="utf-8"))
    for cat in categories:
        for c in json.loads((DATA / "commands" / f"{cat['id']}.json").read_text(encoding="utf-8")):
            for i, ex in enumerate(c["examples"]):
                yield c["id"], f"{c['id']} #{i + 1}", ex
    for t in json.loads((DATA / "tasks.json").read_text(encoding="utf-8")):
        for i, s in enumerate(t["steps"]):
            if "cmd" in s:
                yield None, f"task {t['id']} step {i + 1}", s


def syntax_check(label, cmd):
    text = PLACEHOLDER_RE.sub(lambda m: "PH_" + re.sub(r"[^A-Za-z0-9_]", "_", m.group(1)), cmd)
    res = subprocess.run(["bash", "-n", "-c", text], capture_output=True, text=True, timeout=10)
    return None if res.returncode == 0 else f"{label}: bash -n failed: {res.stderr.strip()}"


def first_words(script):
    """Return the command word of every simple command in a shell snippet."""
    lexer = shlex.shlex(script, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    words = []
    expect_command = True
    try:
        for token in lexer:
            if token and set(token) <= set("|&;()<>"):
                expect_command = token not in ("<", ">", ">>", "<<")
                continue
            if expect_command and not re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", token):
                words.append(token)
                expect_command = False
    except ValueError:
        pass
    return words


def substitute(cmd, values):
    def repl(m):
        name = m.group(1)
        if name not in values:
            raise KeyError(f"no test value for placeholder <{name}>")
        return shlex.quote(str(values[name]))
    return PLACEHOLDER_RE.sub(repl, cmd)


def run_example(base: Path, n: int, label: str, ex: dict, verbose: bool):
    test = ex["test"]
    for tool in test.get("needs", []):
        if not shutil.which(tool):
            return "skip", f"{label}: skipped, {tool} not installed"
    cmd = substitute(ex["cmd"], test.get("vars", {}))
    for word in first_words(cmd):
        if word not in BASH_BUILTINS and not shutil.which(word) and not word.startswith("./"):
            return "skip", f"{label}: skipped, {word} not installed"

    work = base / f"run-{n:03d}"
    build_fixture(work)
    script = "\n".join([
        test.get("before", "") and f"{{ {test['before']}\n}} || exit 97",
        cmd,
        "__lcg_status=$?",
        test.get("after", ""),
        "exit $__lcg_status",
    ])
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": str(work / "home"),
        "LC_ALL": "C",
        "LANG": "C",
        "TERM": "dumb",
        "USER": os.environ.get("USER", "user"),
        "GIT_CONFIG_NOSYSTEM": "1",
    }
    try:
        res = subprocess.run(["bash", "-c", script], cwd=work, env=env, stdin=subprocess.DEVNULL,
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=TIMEOUT)
    except subprocess.TimeoutExpired:
        return "fail", f"{label}: timed out after {TIMEOUT}s"
    out = res.stdout
    problems = []
    if res.returncode == 97:
        problems.append("setup (before) failed")
    elif res.returncode != test.get("status", 0):
        problems.append(f"exit status {res.returncode}, expected {test.get('status', 0)}")
    if "expect" in test and not re.search(test["expect"], out, re.MULTILINE):
        problems.append(f"output does not match {test['expect']!r}")
    if "reject" in test and re.search(test["reject"], out, re.MULTILINE):
        problems.append(f"output unexpectedly matches {test['reject']!r}")
    if problems:
        return "fail", f"{label}: {'; '.join(problems)}\n  script: {script!r}\n  output: {out[-1500:]!r}"
    if verbose:
        print(f"ok   {label}")
    return "pass", None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", help="only run examples of this command id")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    if not shutil.which("bash"):
        print("bash not found; this check runs on Linux only", file=sys.stderr)
        return 2

    entries = list(load_entries())
    syntax_errors = [e for e in (syntax_check(label, ex["cmd"]) for _, label, ex in entries) if e]
    print(f"syntax: {len(entries) - len(syntax_errors)}/{len(entries)} commands parse with bash -n")

    base = Path(tempfile.mkdtemp(prefix=PREFIX))
    counts = {"pass": 0, "fail": 0, "skip": 0}
    messages = []
    try:
        n = 0
        for cid, label, ex in entries:
            if "test" not in ex or (args.only and cid != args.only):
                continue
            n += 1
            outcome, msg = run_example(base, n, label, ex, args.verbose)
            counts[outcome] += 1
            if msg:
                messages.append(msg)
    finally:
        # Remove exactly the directory created above, after sanity checks.
        resolved = base.resolve()
        assert resolved.name.startswith(PREFIX), resolved
        assert resolved.parent == Path(tempfile.gettempdir()).resolve(), resolved
        shutil.rmtree(resolved)

    for msg in messages:
        print(msg)
    for msg in syntax_errors:
        print(msg)
    print(f"fixture examples: {counts['pass']} passed, {counts['fail']} failed, {counts['skip']} skipped")
    return 1 if counts["fail"] or syntax_errors else 0


if __name__ == "__main__":
    sys.exit(main())
