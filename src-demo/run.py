#!/usr/bin/env python3
import argparse
import json
import shutil
import subprocess
from pathlib import Path

import analysis

ROOT_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = ROOT_DIR / "src-demo"
OUT_DIR = SRC_DIR / "out"
TRACE_DIR = SRC_DIR / "traces"
CASE_DIR = SRC_DIR / "testcases"
BIN_INSTR = OUT_DIR / "miniiot_instrumented"

MSG_HELLO = 0x01
MSG_AUTH = 0x02
MSG_WRITE_CONFIG = 0x03

RET_OK = 0
RET_ERR_SHORT = -1
RET_ERR_MAGIC0 = -2
RET_ERR_VERSION = -3
RET_ERR_LENGTH = -4
RET_ERR_CHECKSUM = -5
RET_ERR_UNKNOWN = -6
RET_ERR_PAYLOAD = -7
RET_ERR_MAGIC1 = -8
RET_ERR_AUTH = -20
RET_ERR_BUG_OOB = -100

TEST_CASES = [
    "001_short_input",
    "002_bad_magic",
    "003_bad_version",
    "004_bad_checksum",
    "005_hello_ok",
    "006_auth_ok",
    "007_write_config_without_auth",
    "008_write_config_ok",
    "009_write_config_oob",
]


def make_packet(msg_type: int, flags: int, session_id: int, payload: bytes) -> bytes:
    header = bytes([
        0xA5,
        0x5A,
        0x01,
        msg_type,
        flags,
        session_id,
        len(payload),
    ])
    header_checksum = sum(header) & 0xFF
    payload_checksum = sum(payload) & 0xFF
    return header + bytes([header_checksum]) + payload + bytes([payload_checksum])


def generate_cases() -> None:
    CASE_DIR.mkdir(parents=True, exist_ok=True)

    cases = [
        {
            "id": "001_short_input",
            "description": "Input length is shorter than minimum packet size.",
            "packet": b"\xA5\x5A\x01",
            "expect": {"handler": None, "bug": None, "ret": RET_ERR_SHORT},
            "tags": ["length", "reject"],
        },
        {
            "id": "002_bad_magic",
            "description": "Packet has incorrect magic bytes.",
            "packet": bytearray(make_packet(MSG_HELLO, 0, 1, b"")),
            "expect": {"handler": None, "bug": None, "ret": RET_ERR_MAGIC0},
            "tags": ["magic", "reject"],
        },
        {
            "id": "003_bad_version",
            "description": "Packet has valid magic but unsupported version.",
            "packet": bytearray(make_packet(MSG_HELLO, 0, 1, b"")),
            "expect": {"handler": None, "bug": None, "ret": RET_ERR_VERSION},
            "tags": ["version", "reject"],
        },
        {
            "id": "004_bad_checksum",
            "description": "Packet has bad header or payload checksum.",
            "packet": bytearray(make_packet(MSG_HELLO, 0, 1, b"")),
            "expect": {"handler": None, "bug": None, "ret": RET_ERR_CHECKSUM},
            "tags": ["checksum", "reject"],
        },
        {
            "id": "005_hello_ok",
            "description": "Valid HELLO packet.",
            "packet": make_packet(MSG_HELLO, 0x01, 0x10, b"\x7F"),
            "expect": {"handler": "HELLO", "bug": None, "ret": RET_OK},
            "tags": ["hello", "valid"],
        },
        {
            "id": "006_auth_ok",
            "description": "Valid AUTH packet.",
            "packet": make_packet(MSG_AUTH, 0, 0x22, bytes([0x42, 0x13, 0x37, 0x22 ^ 0x5A])),
            "expect": {"handler": "AUTH", "bug": None, "ret": RET_OK},
            "tags": ["auth", "valid"],
        },
        {
            "id": "007_write_config_without_auth",
            "description": "WRITE_CONFIG packet rejected because context is not authenticated.",
            "packet": make_packet(MSG_WRITE_CONFIG, 0x00, 0x10, bytes([0x02, 0xAB])),
            "expect": {"handler": "WRITE_CONFIG", "bug": None, "ret": RET_ERR_AUTH},
            "tags": ["write_config", "auth", "reject"],
        },
        {
            "id": "008_write_config_ok",
            "description": "WRITE_CONFIG packet with a valid index.",
            "packet": make_packet(MSG_WRITE_CONFIG, 0x80, 0x10, bytes([0x02, 0xAB])),
            "expect": {"handler": "WRITE_CONFIG", "bug": None, "ret": RET_OK},
            "tags": ["write_config", "valid"],
        },
        {
            "id": "009_write_config_oob",
            "description": "WRITE_CONFIG packet with index 16 triggers OOB config write.",
            "packet": make_packet(MSG_WRITE_CONFIG, 0x80, 0x10, bytes([0x10, 0xAB])),
            "expect": {"handler": "WRITE_CONFIG", "bug": "OOB_CONFIG_WRITE", "ret": RET_ERR_BUG_OOB},
            "tags": ["write_config", "oob", "bug"],
        },
    ]

    for case in cases:
        case_dir = CASE_DIR / case["id"]
        case_dir.mkdir(parents=True, exist_ok=True)
        input_path = case_dir / "input.bin"
        meta_path = case_dir / "meta.json"
        packet = case["packet"]
        if isinstance(packet, bytearray):
            if case["id"] == "002_bad_magic":
                packet[0] = 0x00
            elif case["id"] == "003_bad_version":
                packet[2] = 0x02
            elif case["id"] == "004_bad_checksum":
                packet[7] ^= 0xFF
        input_path.write_bytes(bytes(packet))
        meta = {
            "id": case["id"],
            "description": case["description"],
            "protocol": "miniiot",
            "expect": case["expect"],
            "tags": case["tags"],
        }
        meta_path.write_text(json.dumps(meta, indent=2) + "\n")
    print(f"[OK] generated {len(cases)} testcases in {CASE_DIR}")


def build() -> None:
    subprocess.run(["bash", str(SRC_DIR / "build.sh")], check=True)


def read_trace_result(trace_path: Path) -> int | None:
    if not trace_path.exists():
        return None
    result = None
    with trace_path.open("r", encoding="utf-8") as f:
        for line in f:
            event = json.loads(line)
            if event.get("event") == "result":
                result = event.get("ret")
    return result


def run_case(case_id: str) -> tuple[int, int | None]:
    case_dir = CASE_DIR / case_id
    input_path = case_dir / "input.bin"
    trace_path = TRACE_DIR / f"{case_id}.trace.jsonl"
    if not input_path.exists():
        raise FileNotFoundError(f"missing input for {case_id}: {input_path}")
    TRACE_DIR.mkdir(parents=True, exist_ok=True)
    result = subprocess.run([str(BIN_INSTR), str(input_path), str(trace_path)])
    firmware_ret = read_trace_result(trace_path)
    return result.returncode, firmware_ret


def run_all() -> None:
    for case_id in TEST_CASES:
        print(f"Running {case_id}...")
        process_exit, firmware_ret = run_case(case_id)
        print(f"  {case_id} firmware_ret={firmware_ret} process_exit={process_exit}")


def clean() -> None:
    if OUT_DIR.exists():
        shutil.rmtree(OUT_DIR)
    if TRACE_DIR.exists():
        shutil.rmtree(TRACE_DIR)
    print("[OK] cleaned generated output")


def main() -> int:
    parser = argparse.ArgumentParser(description="MiniIoT source-level demo")
    parser.add_argument("command", choices=["gen", "build", "run", "run-all", "analyze", "clean"])
    parser.add_argument("case_id", nargs="?")
    args = parser.parse_args()

    if args.command == "gen":
        generate_cases()
        return 0
    if args.command == "build":
        build()
        return 0
    if args.command == "run":
        if not args.case_id:
            print("case_id required")
            return 1
        process_exit, firmware_ret = run_case(args.case_id)
        print(f"[OK] {args.case_id} firmware_ret={firmware_ret} process_exit={process_exit}")
        return 0
    if args.command == "run-all":
        run_all()
        return 0
    if args.command == "analyze":
        if not args.case_id:
            print("case_id required")
            return 1
        return 0 if analysis.analyze_case(args.case_id) else 1
    if args.command == "clean":
        clean()
        return 0
    return 1

if __name__ == "__main__":
    raise SystemExit(main())
