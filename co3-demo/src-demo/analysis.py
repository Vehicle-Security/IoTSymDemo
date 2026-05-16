#!/usr/bin/env python3
import json
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
CASE_DIR = ROOT_DIR / "src-demo" / "testcases"
TRACE_DIR = ROOT_DIR / "src-demo" / "traces"

try:
    from z3 import BitVec, Solver, sat
    Z3_AVAILABLE = True
except ImportError:
    Z3_AVAILABLE = False


def load_jsonl(path: Path) -> list[dict]:
    events = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            events.append(json.loads(line))
    return events


def summarize_trace(events: list[dict]) -> dict:
    return {
        "handlers": [e["name"] for e in events if e.get("event") == "handler"],
        "bugs": [e["id"] for e in events if e.get("event") == "bug"],
        "branches": sum(1 for e in events if e.get("event") == "branch"),
        "loads": sum(1 for e in events if e.get("event") == "load"),
        "stores": sum(1 for e in events if e.get("event") == "store"),
        "symbolic_ranges": [e for e in events if e.get("event") == "symbolic_range"],
        "result": [e["ret"] for e in events if e.get("event") == "result"][-1:][0] if [e for e in events if e.get("event") == "result"] else None,
    }


def verify_expect(meta: dict, summary: dict) -> dict:
    expect = meta["expect"]
    handler_match = (expect["handler"] is None and not summary["handlers"]) or (
        expect["handler"] is not None and expect["handler"] in summary["handlers"])
    bug_match = (expect["bug"] is None and not summary["bugs"]) or (
        expect["bug"] is not None and expect["bug"] in summary["bugs"])
    ret_match = expect["ret"] == summary["result"]
    return {
        "handler_match": handler_match,
        "bug_match": bug_match,
        "ret_match": ret_match,
        "status": "PASS" if handler_match and bug_match and ret_match else "FAIL",
    }


def print_summary(case_id: str, meta: dict, summary: dict, verify: dict) -> None:
    print(f"Case: {case_id}")
    print(f"Description: {meta.get('description')}")
    print()
    print("Trace summary:")
    print(f"  branches: {summary['branches']}")
    print(f"  loads: {summary['loads']}")
    print(f"  stores: {summary['stores']}")
    print(f"  symbolic ranges: {len(summary['symbolic_ranges'])}")
    print("  handlers:")
    for handler in summary["handlers"]:
        print(f"    - {handler}")
    print("  bugs:")
    for bug in summary["bugs"]:
        print(f"    - {bug}")
    print(f"  result: {summary['result']}")
    print()
    print("Expectation:")
    print(f"  handler: {meta['expect']['handler']}")
    print(f"  bug: {meta['expect']['bug']}")
    print(f"  ret: {meta['expect']['ret']}")
    print()
    print(f"Status: {verify['status']}")
    if verify["status"] == "FAIL":
        if not verify["handler_match"]:
            print(f"  handler mismatch: got {summary['handlers']}")
        if not verify["bug_match"]:
            print(f"  bug mismatch: got {summary['bugs']}")
        if not verify["ret_match"]:
            print(f"  return mismatch: got {summary['result']}")


class Z3SymbolicAnalyzer:
    def __init__(self, events: list[dict]):
        self.events = events
        self.solver = Solver() if Z3_AVAILABLE else None
        self.buffer = [BitVec(f"buf_{i}", 8) for i in range(512)] if Z3_AVAILABLE else None

    def _parse_cmp_event(self, event: dict):
        if not Z3_AVAILABLE:
            return None
        lhs = event.get("lhs")
        rhs = event.get("rhs")
        lhs_val = event.get("lhs_val")
        rhs_val = event.get("rhs_val")
        if lhs.startswith("buf[") and lhs.endswith("]"):
            index = int(lhs[4:-1])
            return self.buffer[index] == lhs_val
        if rhs.startswith("buf[") and rhs.endswith("]"):
            index = int(rhs[4:-1])
            return self.buffer[index] == rhs_val
        return None

    def build_path_constraints(self):
        if not Z3_AVAILABLE:
            return None
        for event in self.events:
            if event.get("event") == "cmp_u8":
                constraint = self._parse_cmp_event(event)
                if constraint is not None:
                    self.solver.add(constraint)
        return self.solver

    def check(self):
        if not Z3_AVAILABLE:
            raise RuntimeError("Z3 is not installed")
        solver = self.build_path_constraints()
        return solver.check() == sat

    def model_input(self):
        if not Z3_AVAILABLE:
            raise RuntimeError("Z3 is not installed")
        if self.solver.check() != sat:
            return None
        model = self.solver.model()
        return bytes([model[self.buffer[i]].as_long() if self.buffer[i] in model else 0 for i in range(16)])


def analyze_case(case_id: str) -> bool:
    meta_path = CASE_DIR / case_id / "meta.json"
    trace_path = TRACE_DIR / f"{case_id}.trace.jsonl"
    if not meta_path.exists() or not trace_path.exists():
        print(f"missing meta or trace for {case_id}")
        return False
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    events = load_jsonl(trace_path)
    summary = summarize_trace(events)
    verify = verify_expect(meta, summary)
    print_summary(case_id, meta, summary, verify)
    if Z3_AVAILABLE:
        analyzer = Z3SymbolicAnalyzer(events)
        sat = analyzer.check()
        print(f"Z3 path constraints satisfiable: {sat}")
    else:
        print("Z3 not available: symbolic constraint check skipped")
    return verify["status"] == "PASS"


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Analyze MiniIoT trace JSONL.")
    parser.add_argument("case_id", help="Test case ID to analyze")
    args = parser.parse_args()

    raise SystemExit(0 if analyze_case(args.case_id) else 1)
