#!/usr/bin/env python3
"""Run every lesson's tests, each in its own process (every lesson has its own main.py).

    python3 scripts/test_lessons.py            # all lessons
    python3 scripts/test_lessons.py 03-the-agent-loop   # filter by path substring
"""
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
needle = sys.argv[1] if len(sys.argv) > 1 else ""
suites = sorted(p for p in ROOT.glob("phases/*/*/code/test_*.py") if needle in str(p))
if not suites:
    sys.exit(f"no lesson tests match {needle!r}")

failed = []
for test in suites:
    lesson = test.parent.parent.relative_to(ROOT)
    proc = subprocess.run([sys.executable, "-m", "unittest", "-q", test.stem],
                          cwd=test.parent, capture_output=True, text=True)
    ok = proc.returncode == 0
    summary = (proc.stderr.strip().splitlines() or ["?"])
    ran = next((line for line in summary if line.startswith("Ran ")), "")
    print(f"{'ok  ' if ok else 'FAIL'}  {lesson}  {ran}")
    if not ok:
        failed.append(lesson)
        print(proc.stdout + proc.stderr)

print(f"\n{len(suites) - len(failed)}/{len(suites)} lesson suites passed")
sys.exit(1 if failed else 0)
