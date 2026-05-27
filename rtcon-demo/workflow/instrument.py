#!/usr/bin/env python3
"""Generate the phase-2 instrumented C target from analysis.json.

Reads demo/output/analysis.json and inserts trace fprintf calls before the
branches and bug markers selected by phase 1.

The trace output is tab-separated text on stderr.  Branch traces capture the
*actual runtime values* so that the solver can extract constraints.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ANALYSIS = ROOT / "demo" / "output" / "analysis.json"
DEFAULT_OUTPUT = ROOT / "demo" / "output" / "instrumented" / "avdtp_target_inst.c"


def indent_of(line: str) -> str:
    return line[: len(line) - len(line.lstrip())]


def _trace_branch_block(item: dict[str, Any], line: int, indent: str) -> list[str]:
    """Generate a compound trace block for a single critical_branch.

    When a branch contains multiple trace_vars they form a || compound
    condition.  Each sub-expression after the first is guarded so that it is
    only evaluated when the preceding sub-expressions did not short-circuit.
    """
    tvars = item.get("trace_vars", [])
    if not tvars:
        return []

    out: list[str] = []
    prev = "_prev"

    for i, tv in enumerate(tvars):
        name = tv["name"]
        expr = tv["expr"]
        cast = tv.get("cast", "")
        fmt = tv["fmt"]
        op = tv["op"]

        if i == 0:
            # first var: evaluate unconditionally
            if tv.get("type") == "pointer":
                if op == "!=":
                    cond = f"({expr} != NULL)"
                elif op == "==":
                    cond = f"({expr} == NULL)"
                else:
                    raise ValueError(f"unsupported pointer op {op!r} for {name}")
            else:
                expected_macro = tv.get("expected", str(tv.get("expected_val", "")))
                if op == "==":
                    cond = f"({expr} == {expected_macro})"
                elif op == "!=":
                    cond = f"({expr} != {expected_macro})"
                else:
                    raise ValueError(f"unsupported value op {op!r} for {name}")

            out.append(f"{indent}{{ int _p0 = {cond};")
        else:
            # subsequent vars: guard evaluation + only trace when prev passed
            if tv.get("type") == "pointer":
                if op == "!=":
                    safe_cond = f"({expr} != NULL)"
                elif op == "==":
                    safe_cond = f"({expr} == NULL)"
                else:
                    raise ValueError(f"unsupported pointer op {op!r} for {name}")
            else:
                expected_macro = tv.get("expected", str(tv.get("expected_val", "")))
                if op == "==":
                    safe_cond = f"({expr} == {expected_macro})"
                elif op == "!=":
                    safe_cond = f"({expr} != {expected_macro})"
                else:
                    raise ValueError(f"unsupported value op {op!r} for {name}")

            # only evaluate when previous var(s) passed (did NOT short-circuit)
            out.append(f"{indent}  int _p{i} = _p{i - 1} ? {safe_cond} : 0;")

    # --- emit fprintf calls (in reverse: guarded vars first, first var last)
    # so that all fprintfs are inside the single outer block
    for i, tv in enumerate(tvars):
        name = tv["name"]
        expr = tv["expr"]
        cast = tv.get("cast", "")
        fmt = tv["fmt"]

        if i > 0:
            out.append(f"{indent}  if (_p{i - 1}) {{")

        if tv.get("type") == "pointer":
            out.append(
                f'{indent}    fprintf(stderr, "RTCON_TRACE\\tbranch\\t{line}\\tvar={name}\\tactual={fmt}\\tpassed=%d\\n",'
            )
            out.append(f"{indent}            {cast}{expr}, _p{i});")
        else:
            expected_macro = tv.get("expected", str(tv.get("expected_val", "")))
            out.append(
                f'{indent}    fprintf(stderr, "RTCON_TRACE\\tbranch\\t{line}\\tvar={name}\\tactual={fmt}\\texpected={fmt}\\tpassed=%d\\n",'
            )
            out.append(f"{indent}            {cast}{expr}, {cast}({expected_macro}), _p{i});")

        if i > 0:
            out.append(f"{indent}  }}")

    out.append(f"{indent}}}")
    return out


def _trace_block(items: list[dict[str, Any]], line: int, indent: str) -> list[str]:
    """Generate trace instrumentation for a single source line.

    Handles both critical_branch items (with trace_vars) and bug_marker items.
    """
    out: list[str] = []
    for item in items:
        hook = item["hook"]
        if hook == "trace_branch":
            out.extend(_trace_branch_block(item, line, indent))
        elif hook == "trace_marker":
            kind = item["kind"]
            source = item["source"]
            reason = item["reason"]
            out.append(
                f'{indent}fprintf(stderr, "RTCON_TRACE\\tmarker\\t{line}\\tkind={kind}\\tsource={source}\\treason={reason}\\n");'
            )
        else:
            raise ValueError(f"unsupported hook: {hook}")
    return out


def instrumentation_points(analysis: dict[str, Any]) -> dict[int, list[dict[str, Any]]]:
    points: dict[int, list[dict[str, Any]]] = {}
    plan = analysis["plan"]
    for section in ("critical_branches", "bug_markers"):
        for item in plan.get(section, []):
            if item.get("instrument"):
                points.setdefault(item["line"], []).append(item)
    return points


def validate_points(lines: list[str], points: dict[int, list[dict[str, Any]]]) -> None:
    for line_no, items in points.items():
        if line_no < 1 or line_no > len(lines):
            raise SystemExit(f"analysis line {line_no} is outside the source file")

        actual = lines[line_no - 1].strip()
        for item in items:
            expected = item["source"].strip()
            if actual != expected:
                raise SystemExit(
                    "analysis/source mismatch at line "
                    f"{line_no}: expected {expected!r}, found {actual!r}"
                )


def add_stdio_include(lines: list[str]) -> list[str]:
    if any(line.strip() == "#include <stdio.h>" for line in lines):
        return lines

    out: list[str] = []
    inserted = False
    for line in lines:
        out.append(line)
        if not inserted and line.strip() == "#include <stdint.h>":
            out.append("#include <stdio.h>")
            inserted = True

    if not inserted:
        out.insert(0, "#include <stdio.h>")
    return out


def instrument_source(source_path: Path, output_path: Path, analysis: dict[str, Any]) -> None:
    lines = source_path.read_text().splitlines()
    points = instrumentation_points(analysis)
    validate_points(lines, points)

    out: list[str] = []
    for line_no, line in enumerate(lines, start=1):
        items = points.get(line_no, [])
        if items:
            out.extend(_trace_block(items, line_no, indent_of(line)))
        out.append(line)

    out = add_stdio_include(out)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(out) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--analysis", type=Path, default=DEFAULT_ANALYSIS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    analysis_path = args.analysis.resolve()
    output_path = args.output.resolve()

    if not analysis_path.exists():
        raise SystemExit(f"missing analysis file: {analysis_path}")

    analysis = json.loads(analysis_path.read_text())
    source_path = ROOT / analysis["target"]
    if not source_path.exists():
        raise SystemExit(f"missing target file: {source_path}")

    instrument_source(source_path, output_path, analysis)
    print(f"wrote {output_path}")


if __name__ == "__main__":
    main()
