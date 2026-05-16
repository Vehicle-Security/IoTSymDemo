#include "sym_iot.h"
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>

static FILE *trace_file = NULL;
static uintptr_t symbolic_start = UINTPTR_MAX;
static uintptr_t symbolic_len = 0;

static void write_json_string(const char *value) {
    fputc('"', trace_file);
    for (const char *p = value; *p; p++) {
        if (*p == '"' || *p == '\\') {
            fputc('\\', trace_file);
            fputc(*p, trace_file);
        } else if (*p == '\n') {
            fputs("\\n", trace_file);
        } else {
            fputc(*p, trace_file);
        }
    }
    fputc('"', trace_file);
}

static int is_symbolic_addr(uintptr_t addr) {
    if (symbolic_start == UINTPTR_MAX) {
        return 0;
    }
    return addr >= symbolic_start && addr < symbolic_start + symbolic_len;
}

static void add_symbolic_range(uintptr_t addr, uint32_t len) {
    if (symbolic_start == UINTPTR_MAX) {
        symbolic_start = addr;
        symbolic_len = len;
    } else {
        uintptr_t start = symbolic_start;
        uintptr_t end = symbolic_start + symbolic_len;
        uintptr_t new_end = addr + len;
        if (addr < start) {
            start = addr;
        }
        if (new_end > end) {
            end = new_end;
        }
        symbolic_start = start;
        symbolic_len = new_end > end ? (new_end - start) : (end - start);
    }
}

void sym_init(const char *trace_path) {
    trace_file = fopen(trace_path, "w");
    if (!trace_file) {
        perror("sym_init");
        exit(1);
    }
}

void sym_close(void) {
    if (trace_file) {
        fclose(trace_file);
        trace_file = NULL;
    }
}

void sym_input_byte(size_t index, uint8_t value) {
    if (!trace_file) return;
    fprintf(trace_file, "{\"event\":\"input_byte\",\"index\":%zu,\"value\":%u}\n", index, value);
    fflush(trace_file);
}

void sym_event(const char *name) {
    if (!trace_file) return;
    fprintf(trace_file, "{\"event\":\"event\",\"name\":");
    write_json_string(name);
    fprintf(trace_file, "}\n");
    fflush(trace_file);
}

void mark_symbolic(uintptr_t addr, uint32_t len) {
    if (!trace_file) return;
    add_symbolic_range(addr, len);
    fprintf(trace_file, "{\"event\":\"symbolic_range\",\"addr\":%zu,\"len\":%u}\n", (size_t)addr, len);
    fflush(trace_file);
}

void inst_load(uintptr_t addr, uint8_t value) {
    if (!trace_file) return;
    if (!is_symbolic_addr(addr)) return;
    fprintf(trace_file, "{\"event\":\"load\",\"addr\":%zu,\"value\":%u}\n", (size_t)addr, value);
    fflush(trace_file);
}

void inst_store(uintptr_t addr, uint8_t value) {
    if (!trace_file) return;
    fprintf(trace_file, "{\"event\":\"store\",\"addr\":%zu,\"value\":%u}\n", (size_t)addr, value);
    add_symbolic_range(addr, 1);
    fflush(trace_file);
}

void inst_branch(int taken, uint32_t lhs, uint32_t rhs, const char *op) {
    if (!trace_file) return;
    fprintf(trace_file, "{\"event\":\"branch\",\"taken\":%s,\"lhs\":%u,\"rhs\":%u,\"op\":", taken ? "true" : "false", lhs, rhs);
    write_json_string(op);
    fprintf(trace_file, "}\n");
    fflush(trace_file);
}

void sym_branch(const char *id, const char *expr, int taken) {
    if (!trace_file) return;
    fprintf(trace_file, "{\"event\":\"branch\",\"id\":");
    write_json_string(id);
    fprintf(trace_file, ",\"expr\":");
    write_json_string(expr);
    fprintf(trace_file, ",\"taken\":%s}\n", taken ? "true" : "false");
    fflush(trace_file);
}

void sym_handler(const char *name) {
    if (!trace_file) return;
    fprintf(trace_file, "{\"event\":\"handler\",\"name\":");
    write_json_string(name);
    fprintf(trace_file, "}\n");
    fflush(trace_file);
}

void sym_cmp_u8(const char *id, const char *lhs, uint8_t lhs_val,
                const char *op, const char *rhs, uint8_t rhs_val,
                int result) {
    if (!trace_file) return;
    fprintf(trace_file, "{\"event\":\"cmp_u8\",\"id\":");
    write_json_string(id);
    fprintf(trace_file, ",\"lhs\":");
    write_json_string(lhs);
    fprintf(trace_file, ",\"lhs_val\":%u,\"op\":", lhs_val);
    write_json_string(op);
    fprintf(trace_file, ",\"rhs\":");
    write_json_string(rhs);
    fprintf(trace_file, ",\"rhs_val\":%u,\"result\":%s}\n", rhs_val, result ? "true" : "false");
    fflush(trace_file);
}

void sym_value_u8(const char *name, uint8_t value) {
    if (!trace_file) return;
    fprintf(trace_file, "{\"event\":\"value_u8\",\"name\":");
    write_json_string(name);
    fprintf(trace_file, ",\"value\":%u}\n", value);
    fflush(trace_file);
}

void sym_value_size(const char *name, size_t value) {
    if (!trace_file) return;
    fprintf(trace_file, "{\"event\":\"value_size\",\"name\":");
    write_json_string(name);
    fprintf(trace_file, ",\"value\":%zu}\n", value);
    fflush(trace_file);
}

void sym_mem_check(const char *id, const char *array_name,
                   size_t index, size_t limit, int ok) {
    if (!trace_file) return;
    fprintf(trace_file, "{\"event\":\"mem_check\",\"id\":");
    write_json_string(id);
    fprintf(trace_file, ",\"array\":");
    write_json_string(array_name);
    fprintf(trace_file, ",\"index\":%zu,\"limit\":%zu,\"ok\":%s}\n", index, limit, ok ? "true" : "false");
    fflush(trace_file);
}

void sym_bug(const char *id, const char *detail) {
    if (!trace_file) return;
    fprintf(trace_file, "{\"event\":\"bug\",\"id\":");
    write_json_string(id);
    fprintf(trace_file, ",\"detail\":");
    write_json_string(detail);
    fprintf(trace_file, "}\n");
    fflush(trace_file);
}

void sym_result(int ret) {
    if (!trace_file) return;
    fprintf(trace_file, "{\"event\":\"result\",\"ret\":%d}\n", ret);
    fflush(trace_file);
}
