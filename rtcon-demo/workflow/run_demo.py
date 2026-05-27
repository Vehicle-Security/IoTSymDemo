#!/usr/bin/env python3
"""RTCON-style AVDTP demo with iterative constraint solving.

Full pipeline:
  CodeQL  ->  facts.json  ->  analysis.json  ->  source instrumentation
  ->  harness generation  ->  compile  ->  round-1 run  ->  trace capture
  ->  Z3 constraint solving  ->  round-2 run  ->  BUG_REACHED

Usage:
  python3 demo/workflow/run_demo.py
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUN_DIR = ROOT / "demo" / "output" / "run"
HARNESS_C = RUN_DIR / "avdtp_harness.c"
HARNESS_BIN = RUN_DIR / "avdtp_harness"
TRACE_R1 = RUN_DIR / "trace_round1.log"
TRACE_R2 = RUN_DIR / "trace_round2.log"
SOLUTION = RUN_DIR / "solution.json"

# first-round seed: all zeros — should be blocked by context gates
INITIAL_SEED = "0000000000"


def run(cmd: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    print("+", " ".join(cmd))
    return subprocess.run(cmd, text=True, capture_output=True, check=check)


def run_step(cmd: list[str]) -> None:
    result = run(cmd)
    if result.stdout:
        print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, end="")


def compile_harness() -> None:
    run_step([
        "cc", "-std=c11", "-g", "-O0", "-fsanitize=address",
        str(HARNESS_C), "-o", str(HARNESS_BIN),
    ])


def main() -> None:
    print("=== RTCON AVDTP Demo ===")
    print("Target: avdtp_process_configuration")
    print("Static analysis: analysis.json (simulated LLM+CodeQL output)")
    print()

    # ---- Phase 1: CodeQL static fact extraction ----------------------------
    run_step(["python3", str(ROOT / "demo" / "workflow" / "codeql" / "run_codeql.py")])

    # ---- Phase 2-4: analysis plan + instrumentation + harness -------------
    run_step(["python3", str(ROOT / "demo" / "workflow" / "make_analysis.py")])
    run_step(["python3", str(ROOT / "demo" / "workflow" / "instrument.py")])
    run_step(["python3", str(ROOT / "demo" / "workflow" / "generate_harness.py")])

    # ---- Phase 5: compile --------------------------------------------------
    compile_harness()

    # ---- Phase 6: round 1 — initial seed -----------------------------------
    print("--- Round 1: initial seed (zeroed) ---")
    result = run([str(HARNESS_BIN), INITIAL_SEED], check=False)
    TRACE_R1.write_text(result.stderr)
    print(result.stderr, end="")

    passed_0 = "passed=0" in result.stderr
    has_asan = "AddressSanitizer" in result.stderr

    if has_asan:
        raise SystemExit("unexpected ASAN in round 1 — seed already triggers bug")
    if not passed_0:
        print("warning: no blocked branches in round 1, all constraints already satisfied")
    else:
        blocked_lines = set()
        for line in result.stderr.splitlines():
            if "passed=0" in line:
                import re
                m = re.search(r"branch\t(\d+)", line)
                if m:
                    blocked_lines.add(m.group(1))
        print(f"RTCON_RESULT BUG_NOT_REACHED (blocked at lines {sorted(blocked_lines)})")
    print()

    # ---- Phase 7: solve ----------------------------------------------------
    print("--- Solving ---")
    run_step([
        "python3", str(ROOT / "demo" / "workflow" / "solve.py"),
        "--trace", str(TRACE_R1),
        "--analysis", str(ROOT / "demo" / "output" / "analysis.json"),
        "--output", str(SOLUTION),
    ])
    solution = json.loads(SOLUTION.read_text())
    solved_hex = solution["input_hex"]
    print(f"Solution: input_hex = {solved_hex}")
    for desc in solution.get("constraints_descriptions", []):
        print(f"  {desc}")
    print()

    # ---- Phase 8: round 2 — solved input -----------------------------------
    print("--- Round 2: solved input ---")
    result = run([str(HARNESS_BIN), solved_hex], check=False)
    TRACE_R2.write_text(result.stderr)
    print(result.stderr, end="")

    passed_0 = "passed=0" in result.stderr
    has_asan = "AddressSanitizer" in result.stderr

    if passed_0:
        raise SystemExit("unexpected blocked branches in round 2 — solver failed")
    if not has_asan:
        raise SystemExit("expected ASAN in round 2 — bug not triggered")

    print("RTCON_RESULT BUG_REACHED (ASAN)")
    print()
    print("=== Demo complete ===")


if __name__ == "__main__":
    main()
