#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

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

typedef struct {
    uint8_t authenticated;
    uint8_t session_id;
    uint8_t config[16];
} iot_ctx_t;

static uint8_t calc_header_checksum(const uint8_t *buf) {
    uint8_t sum = 0;
    for (size_t i = 0; i < 7; i++) {
        sum += buf[i];
    }
    return sum;
}

static uint8_t calc_payload_checksum(const uint8_t *payload, size_t len) {
    uint8_t sum = 0;
    for (size_t i = 0; i < len; i++) {
        sum += payload[i];
    }
    return sum;
}

int process_packet(iot_ctx_t *ctx, const uint8_t *buf, size_t len) {
    if (len < 9) {
        return RET_ERR_SHORT;
    }

    if (buf[0] != MAGIC0) {
        return RET_ERR_MAGIC0;
    }

    if (buf[1] != MAGIC1) {
        return RET_ERR_MAGIC1;
    }

    if (buf[2] != VERSION) {
        return RET_ERR_VERSION;
    }

    uint8_t msg_type = buf[3];
    uint8_t flags = buf[4];
    uint8_t session_id = buf[5];
    uint8_t payload_len = buf[6];

    if ((size_t)(8 + payload_len) >= len) {
        return RET_ERR_LENGTH;
    }

    uint8_t expected_header = calc_header_checksum(buf);
    uint8_t actual_header = buf[7];
    if (expected_header != actual_header) {
        return RET_ERR_CHECKSUM;
    }

    const uint8_t *payload = buf + 8;
    uint8_t actual_payload_checksum = buf[8 + payload_len];
    uint8_t expected_payload_checksum = calc_payload_checksum(payload, payload_len);
    if (expected_payload_checksum != actual_payload_checksum) {
        return RET_ERR_CHECKSUM;
    }

    switch (msg_type) {
    case MSG_HELLO:
        if (payload_len > 1) {
            return RET_ERR_PAYLOAD;
        }

        if ((flags & 0x01) != 0) {
            ctx->session_id = session_id;
        }
        return RET_OK;

    case MSG_AUTH:
        if (payload_len < 4) {
            return RET_ERR_PAYLOAD;
        }
        if (payload[0] == 0x42 && payload[1] == 0x13 && payload[2] == 0x37 && payload[3] == (session_id ^ 0x5a)) {
            ctx->authenticated = 1;
            ctx->session_id = session_id;
            return RET_OK;
        }
        ctx->authenticated = 0;
        return RET_ERR_AUTH;

    case MSG_WRITE_CONFIG:
        if (payload_len < 2) {
            return RET_ERR_PAYLOAD;
        }
        if (!ctx->authenticated) {
            return RET_ERR_AUTH;
        }
        {
            size_t index = payload[0];
            uint8_t value = payload[1];
            if (index < 16) {
                ctx->config[index] = value;
                return RET_OK;
            }
            return RET_ERR_BUG_OOB;
        }

    default:
        return RET_ERR_UNKNOWN;
    }
}

int main(int argc, char **argv) {
    if (argc != 2) {
        fprintf(stderr, "usage: %s <input.bin>\n", argv[0]);
        return 1;
    }

    const char *path = argv[1];
    FILE *f = fopen(path, "rb");
    if (!f) {
        perror("fopen");
        return 1;
    }

    uint8_t buf[MAX_INPUT];
    size_t len = fread(buf, 1, sizeof(buf), f);
    fclose(f);

    iot_ctx_t ctx = {0};
    int ret = process_packet(&ctx, buf, len);
    return ret;
}
