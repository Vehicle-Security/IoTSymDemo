#!/usr/bin/env python3
"""Run the CodeQL stage for the RTCON AVDTP demo.

This script does exactly three things:
1. Create a CodeQL C/C++ database for demo/avdtp_case/avdtp_target.c.
2. Install the query pack dependencies declared in qlpack.yml if needed.
3. Run avdtp_facts.ql against that database.
4. Decode the query result to facts.json for later analysis/instrumentation.

It deliberately stops at "facts". Later stages can convert facts.json into
analysis.json, then use that file to drive source instrumentation.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
CODEQL_DIR = Path(__file__).resolve().parent
CASE_DIR = ROOT / "demo" / "avdtp_case"
OUTPUT_DIR = ROOT / "demo" / "output" / "codeql"
TARGET_C = CASE_DIR / "avdtp_target.c"
QUERY = CODEQL_DIR / "avdtp_facts.ql"
DB_DIR = OUTPUT_DIR / "avdtp-db"
RESULTS_BQRS = OUTPUT_DIR / "facts.bqrs"
RAW_FACTS_JSON = OUTPUT_DIR / "facts.raw.json"
FACTS_JSON = OUTPUT_DIR / "facts.json"


def run(cmd: list[str], *, cwd: Path | None = None) -> None:
    print("+", " ".join(cmd))
    subprocess.run(cmd, cwd=cwd, check=True)


def require_tool(name: str) -> None:
    if shutil.which(name) is None:
        raise SystemExit(f"missing required tool: {name}")


def write_normalized_facts() -> None:
    raw = json.loads(RAW_FACTS_JSON.read_text())
    rows = raw["#select"]["tuples"]
    source_lines = TARGET_C.read_text().splitlines()

    facts = []
    for kind, function, line, text in rows:
        facts.append(
            {
                "kind": kind,
                "function": function,
                "line": line,
                "text": text,
                "source": source_lines[line - 1].strip(),
            }
        )

    FACTS_JSON.write_text(
        json.dumps(
            {
                "target": str(TARGET_C.relative_to(ROOT)),
                "facts": facts,
            },
            indent=2,
        )
        + "\n"
    )
    RAW_FACTS_JSON.unlink()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--reuse-db",
        action="store_true",
        help="reuse an existing avdtp-db instead of recreating it",
    )
    parser.add_argument(
        "--skip-pack-install",
        action="store_true",
        help="skip 'codeql pack install' when dependencies are already present",
    )
    args = parser.parse_args()

    require_tool("codeql")
    require_tool("cc")

    if not TARGET_C.exists():
        raise SystemExit(f"missing target file: {TARGET_C}")
    if not QUERY.exists():
        raise SystemExit(f"missing query file: {QUERY}")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    if DB_DIR.exists() and not args.reuse_db:
        shutil.rmtree(DB_DIR)

    if not DB_DIR.exists():
        run(
            [
                "codeql",
                "database",
                "create",
                str(DB_DIR),
                "--language=cpp",
                f"--source-root={CASE_DIR}",
                "--command=cc -c avdtp_target.c -o /tmp/rtcon_avdtp_target.o",
            ],
            cwd=CASE_DIR,
        )

    if not args.skip_pack_install:
        run(["codeql", "pack", "install"], cwd=CODEQL_DIR)

    run(
        [
            "codeql",
            "query",
            "run",
            str(QUERY),
            f"--database={DB_DIR}",
            f"--output={RESULTS_BQRS}",
        ],
        cwd=CODEQL_DIR,
    )

    run(
        [
            "codeql",
            "bqrs",
            "decode",
            str(RESULTS_BQRS),
            "--format=json",
            f"--output={RAW_FACTS_JSON}",
        ],
        cwd=CODEQL_DIR,
    )

    write_normalized_facts()
    print(f"\nwrote {FACTS_JSON}")


if __name__ == "__main__":
    main()
