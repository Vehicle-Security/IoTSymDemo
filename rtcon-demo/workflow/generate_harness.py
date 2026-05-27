#!/usr/bin/env python3
"""Generate a deterministic harness from the demo analysis and target source.

This is deliberately a small, source-driven generator rather than a generic C
frontend. It supports the patterns used by the current AVDTP demo target:
entry parameters, a scalar gate, a context callback gate, a SEP lookup gate,
and a short net_buf input. The generated harness is therefore reproducible for
this target without embedding a hand-written AVDTP harness.
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ANALYSIS = ROOT / "demo" / "output" / "analysis.json"
DEFAULT_OUTPUT = ROOT / "demo" / "output" / "run" / "avdtp_harness.c"


@dataclass(frozen=True)
class Param:
    c_type: str
    name: str

    @property
    def is_pointer(self) -> bool:
        return "*" in self.c_type

    @property
    def object_type(self) -> str:
        return self.c_type.replace("*", "").strip()


@dataclass(frozen=True)
class CallbackInfo:
    owner_param: str
    owner_field: str
    field_name: str
    ops_type: str
    return_type: str
    args: list[Param]


@dataclass(frozen=True)
class LookupInfo:
    local_name: str
    local_type: str
    function_name: str
    list_name: str
    node_field: str
    id_field_path: str
    input_param: str
    shift: int


@dataclass(frozen=True)
class BufShape:
    param_name: str
    object_type: str
    inner_field: str
    data_field: str
    len_field: str


def plan_items(analysis: dict[str, Any], section: str) -> list[dict[str, Any]]:
    return analysis["plan"][section]


def plan_names(analysis: dict[str, Any], section: str) -> set[str]:
    return {item["name"] for item in plan_items(analysis, section)}


def branch_sources(analysis: dict[str, Any]) -> list[str]:
    return [item["source"] for item in plan_items(analysis, "critical_branches")]


def marker_sources(analysis: dict[str, Any]) -> list[str]:
    return [item["source"] for item in plan_items(analysis, "bug_markers")]


def split_params(text: str) -> list[str]:
    params: list[str] = []
    current: list[str] = []
    depth = 0
    for char in text:
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        if char == "," and depth == 0:
            params.append("".join(current).strip())
            current = []
        else:
            current.append(char)
    tail = "".join(current).strip()
    if tail and tail != "void":
        params.append(tail)
    return params


def parse_param(text: str) -> Param:
    text = " ".join(text.strip().split())
    match = re.match(r"(?P<type>.+?)(?P<stars>\*+)?\s*(?P<name>[A-Za-z_]\w*)$", text)
    if not match:
        raise SystemExit(f"cannot parse C parameter: {text}")
    stars = match.group("stars") or ""
    c_type = f"{match.group('type').strip()} {stars}".strip()
    return Param(c_type=c_type, name=match.group("name"))


def extract_function(source: str, name: str) -> tuple[list[Param], str]:
    pattern = re.compile(
        rf"^\s*(?:static\s+)?[\w\s\*]+\b{name}\s*\((?P<params>.*?)\)\s*\{{",
        re.M | re.S,
    )
    match = pattern.search(source)
    if not match:
        raise SystemExit(f"cannot find target function: {name}")

    start = match.end()
    depth = 1
    pos = start
    while pos < len(source) and depth:
        if source[pos] == "{":
            depth += 1
        elif source[pos] == "}":
            depth -= 1
        pos += 1

    params = [parse_param(item) for item in split_params(match.group("params"))]
    return params, source[start : pos - 1]


def extract_structs(source: str) -> dict[str, str]:
    return {
        match.group("name"): match.group("body")
        for match in re.finditer(
            r"^\s*struct\s+(?P<name>\w+)\s*\{\s*(?P<body>.*?)^\s*\};",
            source,
            re.M | re.S,
        )
    }


def find_struct_field_type(structs: dict[str, str], struct_type: str, field_name: str) -> str:
    struct_name = struct_type.replace("struct ", "").strip()
    body = structs.get(struct_name)
    if body is None:
        raise SystemExit(f"cannot find struct definition: {struct_type}")

    pattern = re.compile(rf"(?P<type>[\w\s]+?\s*\*?)\s*{re.escape(field_name)}\s*;", re.S)
    match = pattern.search(body)
    if not match:
        raise SystemExit(f"cannot find field {field_name} in {struct_type}")
    return " ".join(match.group("type").split())


def find_struct_member_of_type(structs: dict[str, str], struct_type: str, member_type_prefix: str) -> tuple[str, str]:
    struct_name = struct_type.replace("struct ", "").strip()
    body = structs.get(struct_name)
    if body is None:
        raise SystemExit(f"cannot find struct definition: {struct_type}")

    for match in re.finditer(r"(?P<type>struct\s+\w+|uint\d+_t|[A-Za-z_]\w*)\s*(?P<pointer>\*)?\s*(?P<name>\w+)\s*;", body):
        c_type = match.group("type")
        if c_type.startswith(member_type_prefix):
            return c_type, match.group("name")
    raise SystemExit(f"cannot find {member_type_prefix} member in {struct_type}")


def parse_function_pointer(structs: dict[str, str], struct_type: str, field_name: str) -> tuple[str, list[Param]]:
    struct_name = struct_type.replace("struct ", "").strip()
    body = structs.get(struct_name)
    if body is None:
        raise SystemExit(f"cannot find struct definition: {struct_type}")

    pattern = re.compile(
        rf"(?P<ret>[\w\s\*]+?)\(\s*\*\s*{re.escape(field_name)}\s*\)\s*"
        r"\((?P<args>.*?)\)\s*;",
        re.S,
    )
    match = pattern.search(body)
    if not match:
        raise SystemExit(f"cannot find function pointer {field_name} in {struct_type}")
    return_type = " ".join(match.group("ret").split())
    args = [parse_param(item) for item in split_params(match.group("args"))]
    return return_type, args


def infer_callback(source: str, structs: dict[str, str], params: list[Param]) -> CallbackInfo | None:
    for branch in re.finditer(r"(?P<owner>\w+)->(?P<owner_field>\w+)->(?P<field>\w+)\s*==\s*NULL", source):
        owner = branch.group("owner")
        owner_param = next((param for param in params if param.name == owner), None)
        if owner_param is None:
            continue

        ops_field_type = find_struct_field_type(structs, owner_param.object_type, branch.group("owner_field"))
        ops_type = ops_field_type.replace("const ", "").replace("*", "").strip()
        return_type, args = parse_function_pointer(structs, ops_type, branch.group("field"))
        return CallbackInfo(
            owner_param=owner,
            owner_field=branch.group("owner_field"),
            field_name=branch.group("field"),
            ops_type=ops_type,
            return_type=return_type,
            args=args,
        )
    return None


def infer_lookup(function_body: str, source: str) -> LookupInfo | None:
    null_check = re.search(r"(?P<local>\w+)\s*==\s*NULL", function_body)
    if not null_check:
        return None
    local_name = null_check.group("local")

    local_decl = re.search(rf"(?P<type>struct\s+\w+)\s*\*\s*{re.escape(local_name)}\s*;", function_body)
    assignment = re.search(
        rf"{re.escape(local_name)}\s*=\s*(?P<fn>\w+)\s*\(\s*"
        r"net_buf_pull_u8\s*\(\s*(?P<input>\w+)\s*\)\s*>>\s*(?P<shift>\d+)\s*\)\s*;",
        function_body,
    )
    if not local_decl or not assignment:
        return None

    lookup_params, lookup_body = extract_function(source, assignment.group("fn"))
    lookup_param = lookup_params[0].name if lookup_params else ""
    iterator = re.search(
        rf"SYS_SLIST_FOR_EACH_CONTAINER\s*\(\s*&(?P<list>\w+)\s*,\s*{re.escape(local_name)}\s*,\s*(?P<node>\w+)\s*\)",
        lookup_body,
    )
    compare = re.search(
        rf"{re.escape(local_name)}->(?P<field>[\w\.]+)\s*==\s*{re.escape(lookup_param)}",
        lookup_body,
    )
    if not iterator or not compare:
        return None

    return LookupInfo(
        local_name=local_name,
        local_type=local_decl.group("type"),
        function_name=assignment.group("fn"),
        list_name=iterator.group("list"),
        node_field=iterator.group("node"),
        id_field_path=compare.group("field"),
        input_param=assignment.group("input"),
        shift=int(assignment.group("shift")),
    )


def infer_buf_shape(structs: dict[str, str], params: list[Param], analysis: dict[str, Any]) -> BufShape:
    input_names = plan_names(analysis, "input_like")
    buf_param = next((param for param in params if param.name in input_names and param.is_pointer), None)
    if buf_param is None:
        raise SystemExit("cannot infer pointer input parameter for harness")

    inner_type, inner_field = find_struct_member_of_type(structs, buf_param.object_type, "struct ")
    data_type, data_field = find_struct_member_of_type(structs, inner_type, "uint8_t")
    if data_type != "uint8_t":
        raise SystemExit("input buffer data field must be uint8_t for this demo")

    _, len_field = find_struct_member_of_type(structs, inner_type, "uint16_t")
    return BufShape(
        param_name=buf_param.name,
        object_type=buf_param.object_type,
        inner_field=inner_field,
        data_field=data_field,
        len_field=len_field,
    )


def scalar_gate(branches: list[str], params: list[Param]) -> tuple[str, str] | None:
    names = {param.name for param in params if not param.is_pointer}
    for source in branches:
        match = re.search(r"if\s*\(\s*(?P<name>\w+)\s*==\s*(?P<value>[A-Za-z_]\w*)\s*\)", source)
        if match and match.group("name") in names:
            return match.group("name"), match.group("value")
    return None


def emit_comment_list(title: str, values: list[str]) -> list[str]:
    lines = [f"/* {title}:"]
    for value in values:
        lines.append(f" * - {value}")
    lines.append(" */")
    return lines


def emit_callback(callback: CallbackInfo) -> list[str]:
    args = ",\n\t\t\t\t      ".join(f"{arg.c_type} {arg.name}" for arg in callback.args)
    lines = [f"static {callback.return_type} demo_{callback.field_name}({args})", "{"]
    for arg in callback.args:
        lines.append(f"\t(void){arg.name};")
    lines.append(f'\tprintf("RTCON_TRACE callback reached: {callback.field_name}\\n");')
    if callback.return_type != "void":
        lines.append("\treturn 0;")
    lines.extend(["}", ""])
    return lines


def emit_fuzz_entry(
    target_function: str,
    params: list[Param],
    buf_shape: BufShape,
    callback: CallbackInfo | None,
    lookup: LookupInfo | None,
    scalar_name: str | None,
) -> list[str]:
    object_params = [param for param in params if param.is_pointer and param.name != buf_shape.param_name]
    call_args: list[str] = []
    lines: list[str] = [
        "#define DEMO_FLAG_LOOKUP   0x01",
        "#define DEMO_FLAG_CALLBACK 0x02",
        "#define DEMO_FLAG_SHORT    0x04",
        "",
        "int LLVMFuzzerTestOneInput(const uint8_t *data, size_t size)",
        "{",
        *([f"\tstatic const {callback.ops_type} demo_ops = {{",
           f"\t\t.{callback.field_name} = demo_{callback.field_name},",
           "\t};"] if callback else []),
        *[f"\t{param.object_type} {param.name}_obj;" for param in object_params],
        *([f"\t{lookup.local_type} {lookup.local_name}_obj;"] if lookup else []),
        f"\t{buf_shape.object_type} {buf_shape.param_name}_obj;",
        "\tuint8_t input_storage[2] = { 0, 0 };",
        "\tuint8_t short_storage[1] = { 0 };",
        "\tuint8_t flags;",
        "",
        "\tif (size < 4) {",
        "\t\treturn 0;",
        "\t}",
        "",
        "\tflags = data[1];",
        "\tinput_storage[0] = data[3];",
        "\tshort_storage[0] = data[3];",
        "\tif (size > 4) {",
        "\t\tinput_storage[1] = data[4];",
        "\t}",
        "",
    ]
    for param in object_params:
        lines.append(f"\tmemset(&{param.name}_obj, 0, sizeof({param.name}_obj));")
    if lookup:
        lines.append(f"\tmemset(&{lookup.local_name}_obj, 0, sizeof({lookup.local_name}_obj));")
    lines.append(f"\tmemset(&{buf_shape.param_name}_obj, 0, sizeof({buf_shape.param_name}_obj));")
    lines.extend([
        f"\t{buf_shape.param_name}_obj.{buf_shape.inner_field}.{buf_shape.data_field} = input_storage;",
        f"\t{buf_shape.param_name}_obj.{buf_shape.inner_field}.{buf_shape.len_field} = data[2];",
        "",
    ])

    if callback:
        lines.extend([
            "\tif (flags & DEMO_FLAG_CALLBACK) {",
            f"\t\t{callback.owner_param}_obj.{callback.owner_field} = &demo_ops;",
            "\t}",
        ])

    if lookup:
        lines.extend([
            f"\t{lookup.list_name}.head = NULL;",
            "\tif (flags & DEMO_FLAG_LOOKUP) {",
            f"\t\t{lookup.local_name}_obj.{lookup.id_field_path} = (uint8_t)(data[3] >> {lookup.shift});",
            f"\t\t{lookup.local_name}_obj.{lookup.node_field}.next = NULL;",
            f"\t\t{lookup.list_name}.head = &{lookup.local_name}_obj.{lookup.node_field};",
            "\t}",
        ])

    lines.extend([
        "\tif (flags & DEMO_FLAG_SHORT) {",
        f"\t\t{buf_shape.param_name}_obj.{buf_shape.inner_field}.{buf_shape.data_field} = short_storage;",
        "\t}",
        "",
    ])

    for param in params:
        if param.name == buf_shape.param_name:
            call_args.append(f"&{buf_shape.param_name}_obj")
        elif param.is_pointer:
            call_args.append(f"&{param.name}_obj")
        elif scalar_name and param.name == scalar_name:
            call_args.append("data[0]")
        else:
            call_args.append("0")

    lines.extend([
        f"\t{target_function}({', '.join(call_args)});",
        f'\tprintf("RTCON_CASE_DONE remaining_len=%u\\n", {buf_shape.param_name}_obj.{buf_shape.inner_field}.{buf_shape.len_field});',
        "\treturn 0;",
        "}",
        "",
    ])
    return lines


def emit_main() -> list[str]:
    return [
        "static int hex_value(char c)",
        "{",
        "\tif (c >= '0' && c <= '9') return c - '0';",
        "\tif (c >= 'a' && c <= 'f') return c - 'a' + 10;",
        "\tif (c >= 'A' && c <= 'F') return c - 'A' + 10;",
        "\treturn -1;",
        "}",
        "",
        "static int hex_decode(const char *hex, uint8_t *out, size_t out_max)",
        "{",
        "\tsize_t hex_len = strlen(hex);",
        "\tsize_t i;",
        "\tif ((hex_len % 2) != 0 || hex_len / 2 > out_max) return -1;",
        "\tfor (i = 0; i < hex_len / 2; i++) {",
        "\t\tint high = hex_value(hex[i * 2]);",
        "\t\tint low  = hex_value(hex[i * 2 + 1]);",
        "\t\tif (high < 0 || low < 0) return -1;",
        "\t\tout[i] = (uint8_t)((high << 4) | low);",
        "\t}",
        "\treturn (int)(hex_len / 2);",
        "}",
        "",
        "int main(int argc, char **argv)",
        "{",
        "\tuint8_t bytes[256];",
        "\tchar file_buf[4096];",
        "\tint nbytes;",
        "\tconst char *hex_input = NULL;",
        "",
        "\tif (argc == 2 && strcmp(argv[1], \"--solution\") != 0) {",
        "\t\t/* traditional hex-bytes mode */",
        "\t\thex_input = argv[1];",
        "\t} else if (argc == 3 && strcmp(argv[1], \"--solution\") == 0) {",
        "\t\t/* read input_hex from solution.json */",
        "\t\tFILE *f = fopen(argv[2], \"r\");",
        "\t\tif (!f) {",
        '\t\t\tfprintf(stderr, "cannot open solution file: %s\\n", argv[2]);',
        "\t\t\treturn 2;",
        "\t\t}",
        "\t\tsize_t n = fread(file_buf, 1, sizeof(file_buf) - 1, f);",
        "\t\tfclose(f);",
        "\t\tfile_buf[n] = '\\0';",
        "\t\t/* quick scan for \"input_hex\": \"...\" */",
        "\t\tchar *p = strstr(file_buf, \"\\\"input_hex\\\"\");",
        "\t\tif (p) {",
        "\t\t\tp = strchr(p, ':');",
        "\t\t\tif (p) {",
        "\t\t\t\tp = strchr(p, '\"');",
        "\t\t\t\tif (p) { p++;",
        "\t\t\t\t\tchar *q = strchr(p, '\"');",
        "\t\t\t\t\tif (q) *q = '\\0';",
        "\t\t\t\t\thex_input = p;",
        "\t\t\t\t}",
        "\t\t\t}",
        "\t\t}",
        "\t\tif (!hex_input) {",
        '\t\t\tfprintf(stderr, "could not parse input_hex from %s\\n", argv[2]);',
        "\t\t\treturn 2;",
        "\t\t}",
        "\t} else {",
        '\t\tfprintf(stderr, "usage: %s HEX_BYTES\\n", argv[0]);',
        '\t\tfprintf(stderr, "       %s --solution SOLUTION.json\\n", argv[0]);',
        "\t\treturn 2;",
        "\t}",
        "",
        "\tnbytes = hex_decode(hex_input, bytes, sizeof(bytes));",
        "\tif (nbytes < 0) {",
        '\t\tfprintf(stderr, "bad hex input\\n");',
        "\t\treturn 2;",
        "\t}",
        "",
        '\tprintf("RTCON_INPUT %s\\n", hex_input);',
        "\treturn LLVMFuzzerTestOneInput(bytes, (size_t)nbytes);",
        "}",
    ]


def generate_harness(analysis: dict[str, Any]) -> str:
    target_path = ROOT / analysis["target"]
    target_source = target_path.read_text()
    target_function = analysis["target_function"]
    params, function_body = extract_function(target_source, target_function)
    structs = extract_structs(target_source)
    branches = branch_sources(analysis)

    buf_shape = infer_buf_shape(structs, params, analysis)
    callback = infer_callback(function_body, structs, params)
    lookup = infer_lookup(function_body, target_source)
    scalar = scalar_gate(branches, params)
    scalar_name = scalar[0] if scalar else None

    lines: list[str] = [
        "#include <stdio.h>",
        "#include <string.h>",
        "",
        '#include "../instrumented/avdtp_target_inst.c"',
        "",
    ]
    lines.extend(emit_comment_list("Input-like symbols from analysis", sorted(plan_names(analysis, "input_like"))))
    lines.extend(emit_comment_list("Context-like symbols from analysis", sorted(plan_names(analysis, "context_like"))))
    lines.extend(emit_comment_list("Bug markers used as reachability checks", marker_sources(analysis)))
    lines.extend(emit_comment_list("Harness input bytes", [
        "data[0]: scalar branch parameter",
        "data[1]: context flags (lookup/callback/short-buffer)",
        "data[2]: logical input buffer length",
        "data[3..]: bytes used as target buffer storage",
    ]))
    lines.append("")
    if callback:
        lines.extend(emit_callback(callback))
    lines.extend(emit_fuzz_entry(target_function, params, buf_shape, callback, lookup, scalar_name))
    lines.extend(emit_main())
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--analysis", type=Path, default=DEFAULT_ANALYSIS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--solution", type=Path, default=None,
                        help="solution.json from solve.py (reserved for future use)")
    args = parser.parse_args()

    analysis_path = args.analysis.resolve()
    output_path = args.output.resolve()

    if not analysis_path.exists():
        raise SystemExit(f"missing analysis file: {analysis_path}")

    analysis = json.loads(analysis_path.read_text())
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(generate_harness(analysis))
    print(f"wrote {output_path}")


if __name__ == "__main__":
    main()
