#!/usr/bin/env python3
"""Phase-3 constraint solver: parse a round-1 trace, match against
analysis.json trace_vars, build Z3 constraints, and emit solution.json.

All domain knowledge (which flag bit controls which context variable, what
numeric values are needed to trigger the bug) lives in analysis.json.
This script is a purely mechanical solver.

Usage:
  python3 demo/workflow/solve.py \\
      --trace demo/output/run/trace_round1.log \\
      --analysis demo/output/analysis.json \\
      --output demo/output/run/solution.json
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# trace parsing
# ---------------------------------------------------------------------------

TRACE_RE = re.compile(
    r"RTCON_TRACE\t(?P<kind>branch|marker|callback)\t(?P<line>\d+)"
    r"(?:\tvar=(?P<var>[^\t]+))?"
    r"(?:\tactual=(?P<actual>[^\t]+))?"
    r"(?:\texpected=(?P<expected>[^\t]+))?"
    r"\t.*?passed=(?P<passed>\d+)"
)


def parse_trace(path: Path) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    for raw in path.read_text().splitlines():
        m = TRACE_RE.search(raw)
        if m and m.group("kind") == "branch":
            entries.append(m.groupdict())
    return entries


# ---------------------------------------------------------------------------
# constraint extraction  (data-driven — all knowledge from analysis.json)
# ---------------------------------------------------------------------------

def _index_trace_vars(analysis: dict[str, Any]) -> dict[tuple[int, str], dict[str, Any]]:
    """Build (line, name) -> trace_var lookup."""
    idx: dict[tuple[int, str], dict[str, Any]] = {}
    for branch in analysis["plan"]["critical_branches"]:
        for tv in branch.get("trace_vars", []):
            idx[(branch["line"], tv["name"])] = tv
    return idx


def _branches_by_line(analysis: dict[str, Any]) -> dict[int, dict[str, Any]]:
    return {b["line"]: b for b in analysis["plan"]["critical_branches"]}


def extract_failed(
    entries: list[dict[str, str]],
    analysis: dict[str, Any],
) -> list[dict[str, Any]]:
    """Return constraints that need fixing, including short-circuited siblings."""
    tv_index = _index_trace_vars(analysis)
    branches = _branches_by_line(analysis)

    traced: set[tuple[int, str]] = set()
    failed: list[dict[str, Any]] = []
    seen: set[tuple[int, str]] = set()

    for e in entries:
        line = int(e["line"])
        var = e.get("var", "")
        key = (line, var)
        traced.add(key)

        if e["passed"] != "0":
            continue
        if key in seen:
            continue
        seen.add(key)

        tv = tv_index.get(key)
        failed.append({
            "line": line, "var": var,
            "actual": e.get("actual", ""),
            "trace_var": tv,
        })

    # catch up: if any var in a branch failed, also include siblings that were
    # short-circuited (never traced)
    for fc in list(failed):
        branch = branches.get(fc["line"])
        if not branch:
            continue
        for tv in branch.get("trace_vars", []):
            sib = (branch["line"], tv["name"])
            if sib not in traced and sib not in seen:
                seen.add(sib)
                failed.append({
                    "line": branch["line"], "var": tv["name"],
                    "actual": "(short-circuited)",
                    "trace_var": tv,
                })

    return failed


# ---------------------------------------------------------------------------
# solving  (all parameters come from analysis.json data)
# ---------------------------------------------------------------------------

def solve(
    failed: list[dict[str, Any]],
    analysis: dict[str, Any],
) -> dict[str, Any]:
    """Build solution from analysis.json data (no hardcoded flag values)."""

    bug_trigger = analysis.get("bug_trigger", {})
    constraints_descr: list[str] = []

    # --- collect required flag bits from trace_vars --------------------------
    flags = 0
    for fc in failed:
        tv = fc.get("trace_var")
        if not tv:
            continue
        mech = tv.get("context_mechanism", {})
        if mech.get("type") == "flag_bit":
            flags |= int(mech["mask"])
            constraints_descr.append(
                f"line {fc['line']}: {fc['var']} → {mech.get('note', 'set flag')}"
            )
        elif mech.get("type") == "default":
            constraints_descr.append(
                f"line {fc['line']}: {fc['var']} → {mech.get('note', 'default ok')}"
            )
        elif mech.get("type") == "input_byte":
            # numeric constraint handled below
            pass

    # add bug-trigger flags
    bug_flags = int(bug_trigger.get("flag_mask", 0))
    flags |= bug_flags
    if bug_flags:
        constraints_descr.append(
            f"bug trigger: {bug_trigger.get('description', 'set flag')}"
        )

    # --- build Z3 constraints from trace_vars and bug_trigger ----------------
    try:
        import z3  # type: ignore[import-untyped]

        # bit-vector variables for each input byte
        dvars: dict[int, Any] = {}
        solver = z3.Solver()

        # constraints from trace_vars of ALL branches (both passed and failed)
        # — passed ones must stay passed, failed ones must become passed
        for branch in analysis["plan"]["critical_branches"]:
            for tv in branch.get("trace_vars", []):
                mech = tv.get("context_mechanism", {})
                if mech.get("type") != "input_byte":
                    continue
                byte_idx = int(mech["byte"])
                if byte_idx not in dvars:
                    dvars[byte_idx] = z3.BitVec(f"data{byte_idx}", 8)

                expected = int(tv.get("expected_val", 0))
                if tv.get("op") == "==":
                    solver.add(dvars[byte_idx] == expected)
                    constraints_descr.append(
                        f"line {branch['line']}: {tv['name']} == {expected} → data[{byte_idx}] = {expected:#04x}"
                    )
                elif tv.get("op") == "!=":
                    solver.add(dvars[byte_idx] != expected)
                    constraints_descr.append(
                        f"line {branch['line']}: {tv['name']} != {expected} → data[{byte_idx}] != {expected:#04x}"
                    )

        # bug-trigger numeric constraints
        for key, val in bug_trigger.get("numeric_constraints", {}).items():
            m = re.match(r"data\[(\d+)\]", key)
            if m:
                bi = int(m.group(1))
                if bi not in dvars:
                    dvars[bi] = z3.BitVec(f"data{bi}", 8)
                solver.add(dvars[bi] == int(val))
                constraints_descr.append(
                    f"bug trigger: {key} = {val:#04x}"
                )

        # ensure flag byte covers all required bits
        flag_byte = int(bug_trigger.get("flag_byte", 1))
        if flag_byte not in dvars:
            dvars[flag_byte] = z3.BitVec(f"data{flag_byte}", 8)
        solver.add(dvars[flag_byte] == flags)

        result = solver.check()
        z3_model: dict[str, object] = {}
        if str(result) == "sat":
            m = solver.model()
            for bi, dv in dvars.items():
                z3_model[f"data{bi}"] = m.evaluate(dv).as_long()
        else:
            z3_model = {"error": str(result)}
    except ImportError:
        # fallback: compute without Z3
        z3_model = {}
        z3_model[f"data{int(bug_trigger.get('flag_byte', 1))}"] = flags
        for key, val in bug_trigger.get("numeric_constraints", {}).items():
            m = re.match(r"data\[(\d+)\]", key)
            if m:
                z3_model[f"data{m.group(1)}"] = int(val)
        # also copy passed input-byte constraints from trace_vars
        for branch in analysis["plan"]["critical_branches"]:
            for tv in branch.get("trace_vars", []):
                mech = tv.get("context_mechanism", {})
                if mech.get("type") == "input_byte":
                    k = f"data{int(mech['byte'])}"
                    if k not in z3_model:
                        z3_model[k] = int(tv.get("expected_val", 0))
        z3_model["note"] = "Z3 not available — using heuristic solution"

    # --- build input_hex from model -----------------------------------------
    max_byte = max((int(k.replace("data", "")) for k in z3_model if k.startswith("data") and not isinstance(z3_model[k], str)), default=3)
    hex_bytes = []
    for i in range(max_byte + 1):
        val = z3_model.get(f"data{i}", 0)
        hex_bytes.append(f"{int(val):02x}")
    input_hex = "".join(hex_bytes)

    return {
        "round": 1,
        "constraints_found": len(failed),
        "constraints_solved": len([fc for fc in failed if fc.get("trace_var")]),
        "failed_branches": [
            {"line": fc["line"], "var": fc["var"], "actual": fc["actual"]}
            for fc in failed
        ],
        "constraints_descriptions": constraints_descr,
        "input_hex": input_hex,
        "input_fields": {
            f"data[{i}]": {
                "value": int(z3_model.get(f"data{i}", 0)),
                "description": next(
                    (d for d in constraints_descr if f"data[{i}]" in d), ""
                ),
            }
            for i in range(max_byte + 1)
        },
        "z3_model": z3_model,
    }


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Solve RTCON branch constraints")
    parser.add_argument("--trace", type=Path, required=True)
    parser.add_argument("--analysis", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    if not args.trace.exists():
        raise SystemExit(f"missing trace file: {args.trace}")
    if not args.analysis.exists():
        raise SystemExit(f"missing analysis file: {args.analysis}")

    analysis = json.loads(args.analysis.read_text())
    entries = parse_trace(args.trace)
    failed = extract_failed(entries, analysis)

    if not failed:
        print("no failed constraints found — all branches already passed")
        return

    solution = solve(failed, analysis)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(solution, indent=2) + "\n")
    print(f"wrote {args.output}")
    print(f"  constraints found:   {solution['constraints_found']}")
    print(f"  constraints solved:  {solution['constraints_solved']}")
    print(f"  input_hex:           {solution['input_hex']}")


if __name__ == "__main__":
    main()
