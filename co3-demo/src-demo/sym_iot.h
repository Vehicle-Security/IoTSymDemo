#ifndef SYM_IOT_H
#define SYM_IOT_H

#include <stddef.h>
#include <stdint.h>

void sym_init(const char *trace_path);
void sym_close(void);

void sym_input_byte(size_t index, uint8_t value);

void sym_event(const char *name);
void sym_handler(const char *name);

void mark_symbolic(uintptr_t addr, uint32_t len);
void inst_load(uintptr_t addr, uint8_t value);
void inst_store(uintptr_t addr, uint8_t value);
void inst_branch(int taken, uint32_t lhs, uint32_t rhs, const char *op);

void sym_branch(const char *id, const char *expr, int taken);
void sym_cmp_u8(const char *id, const char *lhs, uint8_t lhs_val,
                const char *op, const char *rhs, uint8_t rhs_val,
                int result);

void sym_value_u8(const char *name, uint8_t value);
void sym_value_size(const char *name, size_t value);

void sym_mem_check(const char *id, const char *array_name,
                   size_t index, size_t limit, int ok);

void sym_bug(const char *id, const char *detail);
void sym_result(int ret);

#endif // SYM_IOT_H
