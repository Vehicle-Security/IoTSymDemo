#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "sym_iot.h"

#define MAGIC0  0xA5
#define MAGIC1  0x5A
#define VERSION 0x01

#define MSG_HELLO        0x01
#define MSG_AUTH         0x02
#define MSG_WRITE_CONFIG 0x03

#define RET_OK             0
#define RET_ERR_SHORT     -1
#define RET_ERR_MAGIC0    -2
#define RET_ERR_VERSION   -3
#define RET_ERR_LENGTH    -4
#define RET_ERR_CHECKSUM -5
#define RET_ERR_UNKNOWN   -6
#define RET_ERR_PAYLOAD   -7
#define RET_ERR_MAGIC1    -8
#define RET_ERR_AUTH     -20
#define RET_ERR_BUG_OOB -100

#define MAX_INPUT 512
#define CONFIG_SIZE 16

typedef struct {
    uint8_t authenticated;
    uint8_t session_id;
    uint8_t config[CONFIG_SIZE];
} iot_ctx_t;

static uint8_t sym_read_u8(const uint8_t *ptr, size_t index) {
    uintptr_t addr = (uintptr_t)(ptr + index);
    uint8_t value = ptr[index];
    inst_load(addr, value);
    return value;
}

static uint8_t calc_header_checksum(const uint8_t *buf) {
    uint8_t sum = 0;
    for (size_t i = 0; i < 7; i++) {
        sum += sym_read_u8(buf, i);
    }
    return sum;
}

static uint8_t calc_payload_checksum(const uint8_t *payload, size_t len) {
    uint8_t sum = 0;
    for (size_t i = 0; i < len; i++) {
        sum += sym_read_u8(payload, i);
    }
    return sum;
}

static int trace_return(int ret) {
    sym_result(ret);
    return ret;
}

int process_packet(iot_ctx_t *ctx, const uint8_t *buf, size_t len) {
    mark_symbolic((uintptr_t)buf, (uint32_t)len);

    int ok = (int)(len >= 9);
    inst_branch(ok, (uint32_t)len, 9, ">=");
    if (!ok) {
        return trace_return(RET_ERR_SHORT);
    }

    uint8_t msg_type = sym_read_u8(buf, 3);
    uint8_t flags = sym_read_u8(buf, 4);
    uint8_t session_id = sym_read_u8(buf, 5);
    uint8_t payload_len = sym_read_u8(buf, 6);

    uint8_t value0 = sym_read_u8(buf, 0);
    ok = value0 == MAGIC0;
    inst_branch(ok, value0, MAGIC0, "==");
    if (!ok) {
        return trace_return(RET_ERR_MAGIC0);
    }

    uint8_t value1 = sym_read_u8(buf, 1);
    ok = value1 == MAGIC1;
    inst_branch(ok, value1, MAGIC1, "==");
    if (!ok) {
        return trace_return(RET_ERR_MAGIC1);
    }

    uint8_t value2 = sym_read_u8(buf, 2);
    ok = value2 == VERSION;
    inst_branch(ok, value2, VERSION, "==");
    if (!ok) {
        return trace_return(RET_ERR_VERSION);
    }

    ok = (size_t)(8 + payload_len) < len;
    inst_branch(ok, (uint32_t)(8 + payload_len), (uint32_t)len, "<");
    if (!ok) {
        return trace_return(RET_ERR_LENGTH);
    }

    uint8_t expected_header = calc_header_checksum(buf);
    uint8_t actual_header = sym_read_u8(buf, 7);
    ok = expected_header == actual_header;
    inst_branch(ok, expected_header, actual_header, "==");
    if (!ok) {
        return trace_return(RET_ERR_CHECKSUM);
    }

    const uint8_t *payload = buf + 8;
    uint8_t actual_payload_checksum = sym_read_u8(buf, 8 + payload_len);
    uint8_t expected_payload_checksum = calc_payload_checksum(payload, payload_len);
    ok = expected_payload_checksum == actual_payload_checksum;
    inst_branch(ok, expected_payload_checksum, actual_payload_checksum, "==");
    if (!ok) {
        return trace_return(RET_ERR_CHECKSUM);
    }

    switch (msg_type) {
    case MSG_HELLO:
        sym_handler("HELLO");
        inst_branch(payload_len <= 1, payload_len, 1, "<=");
        if (payload_len > 1) {
            return trace_return(RET_ERR_PAYLOAD);
        }
        if ((flags & 0x01) != 0) {
            ctx->session_id = session_id;
        }
        return trace_return(RET_OK);

    case MSG_AUTH:
        sym_handler("AUTH");
        inst_branch(payload_len >= 4, payload_len, 4, ">=");
        if (payload_len < 4) {
            return trace_return(RET_ERR_PAYLOAD);
        }
        {
            uint8_t auth_user = sym_read_u8(payload, 0);
            uint8_t auth_token0 = sym_read_u8(payload, 1);
            uint8_t auth_token1 = sym_read_u8(payload, 2);
            uint8_t auth_token2 = sym_read_u8(payload, 3);

            int user_ok = auth_user == 0x42;
            inst_branch(user_ok, auth_user, 0x42, "==");
            int token0_ok = auth_token0 == 0x13;
            inst_branch(token0_ok, auth_token0, 0x13, "==");
            int token1_ok = auth_token1 == 0x37;
            inst_branch(token1_ok, auth_token1, 0x37, "==");

            uint8_t expected = session_id ^ 0x5a;
            int token2_ok = auth_token2 == expected;
            inst_branch(token2_ok, auth_token2, expected, "==");
            if (user_ok && token0_ok && token1_ok && token2_ok) {
                ctx->authenticated = 1;
                ctx->session_id = session_id;
                return trace_return(RET_OK);
            }
        }
        ctx->authenticated = 0;
        return trace_return(RET_ERR_AUTH);

    case MSG_WRITE_CONFIG:
        sym_handler("WRITE_CONFIG");
        inst_branch(payload_len >= 2, payload_len, 2, ">=");
        if (payload_len < 2) {
            return trace_return(RET_ERR_PAYLOAD);
        }
        /*
         * One input file contains one packet, so this demo uses flags bit 7
         * to simulate a context that was authenticated by an earlier packet.
         */
        if (flags & 0x80) {
            ctx->authenticated = 1;
        }
        if (!ctx->authenticated) {
            return trace_return(RET_ERR_AUTH);
        }
        {
            size_t index = sym_read_u8(payload, 0);
            uint8_t value = sym_read_u8(payload, 1);
            int mem_ok = index < CONFIG_SIZE;
            inst_branch(mem_ok, (uint32_t)index, CONFIG_SIZE, "<");
            if (!mem_ok) {
                sym_bug("OOB_CONFIG_WRITE", "config index out of bounds");
                return trace_return(RET_ERR_BUG_OOB);
            }
            inst_store((uintptr_t)(&ctx->config[index]), value);
            ctx->config[index] = value;
            return trace_return(RET_OK);
        }

    default:
        sym_handler("UNKNOWN");
        return trace_return(RET_ERR_UNKNOWN);
    }
}

int main(int argc, char **argv) {
    if (argc != 3) {
        fprintf(stderr, "usage: %s <input.bin> <trace.jsonl>\n", argv[0]);
        return 1;
    }

    const char *input_path = argv[1];
    const char *trace_path = argv[2];
    FILE *f = fopen(input_path, "rb");
    if (!f) {
        perror("fopen");
        return 1;
    }

    uint8_t buf[MAX_INPUT];
    size_t len = fread(buf, 1, sizeof(buf), f);
    fclose(f);

    sym_init(trace_path);
    iot_ctx_t ctx = {0};
    int ret = process_packet(&ctx, buf, len);
    sym_close();
    return ret;
}
