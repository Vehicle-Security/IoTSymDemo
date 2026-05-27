/*
 * RTCON demo target extracted from Zephyr AVDTP.
 *
 * Source files saved under demo/avdtp_case/zephyr_sources/:
 * - subsys/bluetooth/host/classic/avdtp.c
 * - subsys/bluetooth/host/classic/avdtp_internal.h
 * - include/zephyr/bluetooth/classic/avdtp.h
 * - include/zephyr/net/buf.h
 *
 * The extracted source-code functions are kept below:
 * - avdtp_get_sep()
 * - avdtp_process_configuration()
 *
 * Lines added only to make this standalone demo compile are marked with a
 * "DEMO SUPPORT" comment on the line immediately above the added declaration,
 * definition, macro, or wrapper.
 */

/* DEMO SUPPORT: standard headers replacing Zephyr's include stack. */
#include <stddef.h>
#include <stdint.h>

/* DEMO SUPPORT: errno value used by the extracted Zephyr function. */
#define ENOTSUP 95

/* DEMO SUPPORT: CONTAINER_OF replacement used by Zephyr list macros. */
#define CONTAINER_OF(ptr, type, member) \
	((type *)((char *)(ptr) - offsetof(type, member)))

/* DEMO SUPPORT: sys_snode_t replacement used by struct bt_avdtp_sep. */
typedef struct sys_snode {
	struct sys_snode *next;
} sys_snode_t;

/* DEMO SUPPORT: sys_slist_t replacement used by avdtp_get_sep(). */
typedef struct {
	sys_snode_t *head;
} sys_slist_t;

/* DEMO SUPPORT: Zephyr SYS_SLIST_FOR_EACH_CONTAINER replacement. */
#define SYS_SLIST_FOR_EACH_CONTAINER(list, var, member) \
	for (sys_snode_t *_node = (list)->head; \
	     _node != NULL && ((var) = CONTAINER_OF(_node, __typeof__(*(var)), member)); \
	     _node = _node->next)

/* DEMO SUPPORT: minimal net_buf_simple shape required by net_buf_pull_u8(). */
struct net_buf_simple {
	uint8_t *data;
	uint16_t len;
};

/* DEMO SUPPORT: minimal net_buf shape preserving Zephyr's buf->b access. */
struct net_buf {
	struct net_buf_simple b;
};

/* DEMO SUPPORT: Zephyr declares net_buf_simple_pull_u8() elsewhere. */
uint8_t net_buf_simple_pull_u8(struct net_buf_simple *buf)
{
	buf->len -= 1;
	return *buf->data++;
}

static inline uint8_t net_buf_pull_u8(struct net_buf *buf)
{
	return net_buf_simple_pull_u8(&buf->b);
}

enum sep_state {
	AVDTP_IDLE = 0,
	AVDTP_CONFIGURED,
	/* establishing the transport sessions. */
	AVDTP_OPENING,
	AVDTP_OPEN,
	AVDTP_STREAMING,
	AVDTP_CLOSING,
	AVDTP_ABORTING,
};

/* DEMO SUPPORT: copied value from Zephyr enum bt_avdtp_err_code. */
#define BT_AVDTP_BAD_STATE 0x31

/* DEMO SUPPORT: reduced from Zephyr struct bt_avdtp_sep_info to fields used here. */
struct bt_avdtp_sep_info {
	/** Stream End Point ID that is the identifier of the stream endpoint */
	uint8_t id:6;
};

/* AVDTP SIGNAL HEADER - MESSAGE TYPE */
#define BT_AVDTP_CMD        0x00

/* DEMO SUPPORT: forward declaration used by Zephyr AVDTP structures. */
struct bt_avdtp;

/* DEMO SUPPORT: reduced from Zephyr struct bt_avdtp_sep to fields used here. */
struct bt_avdtp_sep {
	/** Stream End Point information */
	struct bt_avdtp_sep_info sep_info;
	/** SEP state */
	uint8_t state;
	/* Internally used list node */
	sys_snode_t _node;
};

/* DEMO SUPPORT: reduced from Zephyr struct bt_avdtp_ops_cb to field used here. */
struct bt_avdtp_ops_cb {
	int (*set_configuration_ind)(struct bt_avdtp *session, struct bt_avdtp_sep *sep,
		uint8_t int_seid, struct net_buf *buf, uint8_t *errcode);
};

/* DEMO SUPPORT: reduced from Zephyr struct bt_avdtp to field used here. */
struct bt_avdtp {
	const struct bt_avdtp_ops_cb *ops;
};

/* DEMO SUPPORT: global SEP list from avdtp.c, kept standalone here. */
static sys_slist_t seps;

static struct bt_avdtp_sep *avdtp_get_sep(uint8_t stream_endpoint_id)
{
	struct bt_avdtp_sep *sep = NULL;

	SYS_SLIST_FOR_EACH_CONTAINER(&seps, sep, _node) {
		if (sep->sep_info.id == stream_endpoint_id) {
			break;
		}
	}

	return sep;
}

static void avdtp_process_configuration(struct bt_avdtp *session,
				struct net_buf *buf, uint8_t msg_type, uint8_t tid)
{
	if (msg_type == BT_AVDTP_CMD) {
		int err = 0;
		struct bt_avdtp_sep *sep;
		uint8_t error_code = 0;

		sep = avdtp_get_sep(net_buf_pull_u8(buf) >> 2);
		if ((sep == NULL) || (session->ops->set_configuration_ind == NULL)) {
			err = -ENOTSUP;
		} else {
			if (sep->state == AVDTP_STREAMING) {
				err = -ENOTSUP;
				error_code = BT_AVDTP_BAD_STATE;
			} else {
				uint8_t int_seid;

				/* INT Stream Endpoint ID */
				int_seid = net_buf_pull_u8(buf);
				err = session->ops->set_configuration_ind(session,
						sep, int_seid, buf, &error_code);
			}
		}
		(void)err;
		(void)error_code;
		(void)tid;
	}
}
