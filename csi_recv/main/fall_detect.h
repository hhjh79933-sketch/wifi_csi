#pragma once
/* fall_detect.h — CSI 阈值跌倒检测 + WS2812 RGB LED + 云端事件上报 */

#include <stdint.h>
#include <stdbool.h>

#ifdef __cplusplus
extern "C" {
#endif

/** 事件回调类型：0=跌倒确认, 1=疑似跌倒, 2=跌倒恢复 */
typedef void (*fall_event_cb_t)(int event_type);

void fall_detect_init(void);
void fall_detect_process_frame(const int8_t *csi_buf, uint16_t len, uint32_t ts_ms);
void fall_detect_tick(void);
void fall_detect_set_event_callback(fall_event_cb_t cb);
const char *fall_detect_state_str(void);

#ifdef __cplusplus
}
#endif
