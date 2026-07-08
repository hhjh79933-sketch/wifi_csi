/*
 * SPDX-FileCopyrightText: 2025 Espressif Systems (Shanghai) CO LTD
 *
 * SPDX-License-Identifier: Apache-2.0
 */
/* Get Start Example

   This example code is in the Public Domain (or CC0 licensed, at your option.)

   Unless required by applicable law or agreed to in writing, this
   software is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR
   CONDITIONS OF ANY KIND, either express or implied.
*/

#include <stdio.h>
#include <string.h>
#include <stdlib.h>

/*
 * 本文件功能概览：
 * 1) 作为 Wi-Fi STA 连接热点，等待 DHCP 获取 IP；
 * 2) 启动 UDP 心跳任务：周期性向服务器上报在线信息；
 * 3) 开启 Wi-Fi CSI 接收：在 CSI 回调中做轻量处理（过滤/拷贝/入队）；
 * 4) 启动 CSI 处理任务：滑窗统计特征（简化为方差均值）并运行状态机，状态变化时通过 UDP 上报事件。
 *
 * 约束：CSI 回调处于 Wi-Fi 驱动上下文，必须尽量短小，避免重计算/阻塞。
 */

// Ensure ESP-IDF Kconfig values (CONFIG_*) are visible in this translation unit.
#include "sdkconfig.h"

#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/event_groups.h"

#include "nvs_flash.h"

#include "esp_mac.h"
#include "rom/ets_sys.h"
#include "esp_log.h"
#include "esp_event.h"
#include "esp_system.h"
#include "esp_wifi.h"
#include "esp_netif.h"
#include "esp_now.h"

#include "lwip/sockets.h"
#include "lwip/inet.h"
#include "lwip/netdb.h"

#include "fall_detect.h"

// ===== 用户自定义WiFi和UDP参数 =====
/*
 * WIFI_SSID/WIFI_PASS:
 *   目标热点 SSID/密码（设备作为 STA 连接）。
 * UDP_SERVER_IP/UDP_SERVER_PORT:
 *   UDP 上报服务器地址：用于心跳与 CSI 状态事件。
 */
// ── STA（连手机热点，用于心跳/结果上传）──
#define WIFI_STA_SSID     "YOUR_SSID"
#define WIFI_STA_PASS     "YOUR_PASSWORD"
// ── AP（发送板直连，采集 CSI）──
#define WIFI_AP_SSID      "csi_recv"
#define WIFI_AP_PASS      "12345678"
#define WIFI_AP_CHANNEL   11
#define WIFI_AP_MAX_CONN  1
// ── UDP 上报 ──
#define UDP_SERVER_IP     "YOUR_SERVER_IP"
#define UDP_SERVER_PORT   9000
// Heartbeat is auxiliary: keep it low-frequency to reduce noise/cost.
#define HB_INTERVAL_MS  (60 * 1000)
// ===================================

#define CONFIG_LESS_INTERFERENCE_CHANNEL   11
#if CONFIG_IDF_TARGET_ESP32C5 || CONFIG_IDF_TARGET_ESP32C6
#define CONFIG_WIFI_BAND_MODE   WIFI_BAND_MODE_2G_ONLY
#define CONFIG_WIFI_2G_BANDWIDTHS           WIFI_BW_HT40
#define CONFIG_WIFI_5G_BANDWIDTHS           WIFI_BW_HT40
#define CONFIG_WIFI_2G_PROTOCOL             WIFI_PROTOCOL_11N
#define CONFIG_WIFI_5G_PROTOCOL             WIFI_PROTOCOL_11N
#define CONFIG_ESP_NOW_PHYMODE           WIFI_PHY_MODE_HT40
#else
#define CONFIG_WIFI_BANDWIDTH           WIFI_BW_HT20
#endif
#define CONFIG_ESP_NOW_RATE             WIFI_PHY_RATE_MCS0_LGI
#define CONFIG_FORCE_GAIN                   1
#if CONFIG_IDF_TARGET_ESP32C5
#define CSI_FORCE_LLTF                      0
#endif
#if CONFIG_IDF_TARGET_ESP32S3 || CONFIG_IDF_TARGET_ESP32C3 || CONFIG_IDF_TARGET_ESP32C5 || CONFIG_IDF_TARGET_ESP32C6
#define CONFIG_GAIN_CONTROL                 1
#endif
static const char *TAG = "csi_recv";

// ===== 模式开关 =====
/*
 * CSI_RAW_DUMP_MODE:
 *   1 = 原始 CSI 采集模式（采集训练数据用）
 *       - 停用 FSM
 *       - 通过串口 printf 输出 hex 行（不走 WiFi，避免干扰 CSI 质量）
 *   0 = 推理模式（部署模型后使用）
 *       - 运行 csi_fsm_task / 模型推理，通过 UDP 上报事件
 *
 * 串口输出格式（一行一条）：
 *   CSIRAW <seq> <t_ms> <rssi> <len> <hex>
 * PC 端采集方式：
 *   idf.py monitor | tee csi_dump.txt
 *   或用 Python pyserial 直接读 COM 口
 */
#define CSI_RAW_DUMP_MODE       1

/*
 * FALL_DETECT_ENABLE: 启用跌倒检测 + WS2812 RGB LED (GPIO48)
 *   1 = 启用
 *   0 = 禁用
 */
#define FALL_DETECT_ENABLE       1

#if CSI_RAW_DUMP_MODE
/*
 * 每包 CSI 最大 hex 长度（2 hex chars per byte + ' ' + '\0'）
 * 串口 printf 用，不占额外静态 buffer，用栈上小缓冲区即可
 */
#define CSI_HEX_LINE_BYTES      (CSI_BUF_MAX_LEN * 2 + 80)
#endif
// ===================================

// ===== Step 2: CSI queue + simple FSM (event-based) =====
#define CSI_QUEUE_LEN          128
#define CSI_BUF_MAX_LEN        384

/*
 * CSI_QUEUE_LEN:
 *   CSI 回调入队长度。过小会导致 drop 增加；过大占用 RAM。
 * CSI_BUF_MAX_LEN:
 *   每包 CSI 最大拷贝长度（避免在队列里存超大包）。超过会截断并计数 trunc。
 */

// Step 2-A: temporarily disable CSI peer MAC filtering to learn info->mac
#define CSI_FILTER_DISABLE_MS  (10 * 1000)
#define CSI_DEBUG_MAC_SLOTS    6

#define FEATURE_WINDOW_MS      1000
#define FEATURE_STEP_MS        200

/*
 * FEATURE_WINDOW_MS / FEATURE_STEP_MS:
 *   特征滑动窗口长度与步进。
 *   - 窗口更长：更平滑但响应更慢
 *   - 步进更小：更灵敏但 CPU 负载更高
 */

// Thresholds (tune on-site)
#define FEAT_MOTION_TH         210.0f
#define FEAT_STILL_TH          190.0f
#define FALL_DELTA_TH          900.0f
#define FALL_STILL_CONFIRM_MS  5000

/*
 * 阈值调参提示（需要现场标定）：
 * FEAT_STILL_TH:
 *   静止判定阈值（特征低于此值 -> STILL）。
 * FEAT_MOTION_TH:
 *   运动判定阈值（特征高于此值 -> MOTION）。
 * FALL_DELTA_TH:
 *   |feat - last_feat| 的跳变阈值，超过触发 SUSPECT_FALL。
 * FALL_STILL_CONFIRM_MS:
 *   进入 SUSPECT_FALL 后，持续静止这么久才确认跌倒。
 */

typedef struct {
    uint32_t local_ts_ms;
    int8_t rssi;
    uint16_t len;
    int8_t buf[CSI_BUF_MAX_LEN];
} csi_frame_t;

/*
 * csi_frame_t:
 *   从 wifi_csi_info_t 抽取并复制的 CSI 数据包（用于队列传递）。
 *   - local_ts_ms: 本地时间戳（ms），用于滑窗统计
 *   - rssi:        收包 RSSI（调试/质量评估用）
 *   - len/buf:     CSI 原始字节流（按上限截断）
 */

typedef enum {
    FSM_STILL = 0,
    FSM_MOTION,
    FSM_SUSPECT_FALL,
    FSM_CONFIRMED_FALL,
} fsm_state_t;

/*
 * fsm_state_t:
 *   简易状态机输出：
 *   - STILL:         静止
 *   - MOTION:        运动
 *   - SUSPECT_FALL:  疑似跌倒（出现明显跳变）
 *   - CONFIRMED_FALL:确认跌倒（疑似后持续静止确认）
 */

static QueueHandle_t s_csi_queue;
static uint32_t s_csi_cb_count;
static uint32_t s_csi_rx_count;
static uint32_t s_csi_enqueued;
static uint32_t s_csi_dropped;
static uint32_t s_csi_truncated;
static uint16_t s_csi_max_info_len;
static uint32_t s_csi_peer_filtered;
static uint32_t s_csi_invalid;
static uint32_t s_csi_queue_missing;

/*
 * 统计计数器（每秒在 csi_fsm_task 中打印一次）：
 *   cb      : CSI 回调次数（驱动侧是否在产出 CSI）
 *   rx      : 通过过滤后进入处理链路的包数
 *   enq/drop: 入队成功/失败（队列满会 drop）
 *   trunc   : CSI 包被截断次数（超过 CSI_BUF_MAX_LEN）
 *   maxlen  : 观测到的 info->len 最大值（便于评估缓冲区）
 *   filt    : 因 peer MAC 过滤丢弃的包数
 *   inv     : 回调参数异常次数
 *   qmiss   : 队列尚未创建时回调来包次数
 */

static uint32_t s_csi_filter_disable_until_ms;
static uint8_t s_csi_src_macs[CSI_DEBUG_MAC_SLOTS][6];
static uint32_t s_csi_src_counts[CSI_DEBUG_MAC_SLOTS];
static uint8_t s_csi_src_used;
static uint32_t s_csi_src_other;

/*
 * CSI 源 MAC 观察：
 *   前 CSI_FILTER_DISABLE_MS 关闭 peer 过滤，统计 info->mac 出现频率，
 *   用于确认“应该过滤哪个 MAC”（不同目标/模式下 info->mac 可能不是 AP BSSID）。
 */

// Ring buffer storage (static to avoid task stack overflow)
#define CSI_RING_SIZE          256
static float s_var_ring[CSI_RING_SIZE];
static uint32_t s_ts_ring[CSI_RING_SIZE];

static void csi_fsm_task(void *arg);
static void csi_raw_sender_task(void *arg);
static void udp_send_json_event(int sock, const struct sockaddr_in *dest_addr, const char *json);
// =======================================================

static uint8_t s_csi_peer_mac[6] = {0};  // 发送板的 MAC（直连 AP 时学到）
static bool s_csi_peer_mac_set;

static EventGroupHandle_t s_wifi_event_group;
#define WIFI_GOTIP_BIT BIT0
static int s_retry_num;

static const char *wifi_disconnect_reason_str(uint16_t reason)
{
    switch (reason) {
    case WIFI_REASON_ASSOC_TOOMANY: return "ASSOC_TOOMANY";
    case WIFI_REASON_CONNECTION_FAIL: return "CONNECTION_FAIL";
    case WIFI_REASON_HANDSHAKE_TIMEOUT: return "HANDSHAKE_TIMEOUT";
    case WIFI_REASON_4WAY_HANDSHAKE_TIMEOUT: return "4WAY_HANDSHAKE_TIMEOUT";
    case WIFI_REASON_DISASSOC_DUE_TO_INACTIVITY: return "INACTIVITY";
    case WIFI_REASON_AUTH_EXPIRE: return "AUTH_EXPIRE";
    case WIFI_REASON_ASSOC_LEAVE: return "ASSOC_LEAVE";
    default: return "UNKNOWN";
    }
}

static void csi_raw_sender_task(void *arg)
{
    (void)arg;

    /*
     * CSI 原始数据采集任务（CSI_RAW_DUMP_MODE=1 时启用）：
     *   - 从 CSI 队列取帧
     *   - 串口 printf 输出 hex 行（不走 WiFi，不干扰 CSI 质量）
     *   - 格式：CSIRAW <seq> <t_ms> <rssi> <len> <hex>
     *   - 每秒打印统计到 stderr（ESP_LOGI），统计信息不混入数据
     */

    // 栈上 hex 行缓冲区（每字节 → 2 hex，+ \"CSIRAW \" 前缀 + 结尾）
    char hex_line[CSI_HEX_LINE_BYTES];
    uint32_t seq = 0;
    uint32_t sent = 0;
    uint32_t last_stat_ms = 0;

    // 等 WiFi 连上再开始（不严格要求有 IP，但连上了至少说明 RF 在工作）
    ESP_LOGI(TAG, "CSI raw serial dump started (waiting for WiFi connect)...");

    while (true) {
        csi_frame_t frame;
        if (xQueueReceive(s_csi_queue, &frame, pdMS_TO_TICKS(200)) != pdTRUE) {
            uint32_t now_ms = esp_log_timestamp();
            if ((now_ms - last_stat_ms) >= 1000) {
                last_stat_ms = now_ms;
                UBaseType_t q_waiting = (s_csi_queue != NULL) ? uxQueueMessagesWaiting(s_csi_queue) : 0;
                ESP_LOGI(TAG, "CSI serial: cb=%lu rx=%lu enq=%lu drop=%lu trunc=%lu filt=%lu inv=%lu out=%lu q=%lu state=%s",
                         (unsigned long)s_csi_cb_count,
                         (unsigned long)s_csi_rx_count,
                         (unsigned long)s_csi_enqueued,
                         (unsigned long)s_csi_dropped,
                         (unsigned long)s_csi_truncated,
                         (unsigned long)s_csi_peer_filtered,
                         (unsigned long)s_csi_invalid,
                         (unsigned long)sent,
                         (unsigned long)q_waiting,
                         fall_detect_state_str());
            }
#if FALL_DETECT_ENABLE
            fall_detect_tick();   /* LED 闪烁在主循环中驱动，不用定时器 */
#endif
            continue;
        }

#if FALL_DETECT_ENABLE
        /* 跌倒检测：传入原始 CSI 字节 */
        fall_detect_process_frame(frame.buf, frame.len, frame.local_ts_ms);
#endif

        // 构建 hex 行: "CSIRAW <seq> <t_ms> <rssi> <len> <hex>"
        int off = snprintf(hex_line, sizeof(hex_line),
                           "CSIRAW %lu %lu %d %u ",
                           (unsigned long)seq,
                           (unsigned long)frame.local_ts_ms,
                           (int)frame.rssi,
                           (unsigned)frame.len);
        seq++;

        // hex encode CSI buffer
        for (uint16_t i = 0; i < frame.len && off < (int)sizeof(hex_line) - 3; i++) {
            off += snprintf(hex_line + off, sizeof(hex_line) - (size_t)off,
                           "%02x", (unsigned char)frame.buf[i]);
        }
        if (off < (int)sizeof(hex_line)) {
            hex_line[off] = '\n';
            hex_line[off + 1] = '\0';
        }

        // 输出到串口（标准输出，对应 UART0/USB-CDC）
        fputs(hex_line, stdout);
        fflush(stdout);
        sent++;

        // 每秒打印统计到 ESP_LOGI（走 stderr，不混入 stdout 数据流）
        uint32_t now_ms = esp_log_timestamp();
        if ((now_ms - last_stat_ms) >= 1000) {
            last_stat_ms = now_ms;
            UBaseType_t q_waiting = (s_csi_queue != NULL) ? uxQueueMessagesWaiting(s_csi_queue) : 0;
            ESP_LOGI(TAG, "CSI serial: cb=%lu rx=%lu enq=%lu drop=%lu trunc=%lu filt=%lu inv=%lu out=%lu q=%lu",
                     (unsigned long)s_csi_cb_count,
                     (unsigned long)s_csi_rx_count,
                     (unsigned long)s_csi_enqueued,
                     (unsigned long)s_csi_dropped,
                     (unsigned long)s_csi_truncated,
                     (unsigned long)s_csi_peer_filtered,
                     (unsigned long)s_csi_invalid,
                     (unsigned long)sent,
                     (unsigned long)q_waiting);
        }
    }
}

static void udp_heartbeat_task(void *arg)
{
    (void)arg;

    /*
     * UDP 心跳：
     *   - 等待 STA 获取 IP 后开始发送
    *   - 每 HB_INTERVAL_MS 发一条 JSON 心跳，便于服务器确认链路可用与设备在线
     *   - 若丢 IP，会退出内层循环并重建 socket
     */

    while (true) {
        /* Wait until we have an IP address */
        xEventGroupWaitBits(s_wifi_event_group, WIFI_GOTIP_BIT, pdFALSE, pdTRUE, portMAX_DELAY);

        struct sockaddr_in dest_addr = { 0 };
        dest_addr.sin_family = AF_INET;
        dest_addr.sin_port = htons(UDP_SERVER_PORT);
        dest_addr.sin_addr.s_addr = inet_addr(UDP_SERVER_IP);

        int sock = socket(AF_INET, SOCK_DGRAM, IPPROTO_IP);
        if (sock < 0) {
            ESP_LOGE(TAG, "UDP heartbeat: socket() failed errno=%d", errno);
            vTaskDelay(pdMS_TO_TICKS(1000));
            continue;
        }

        uint8_t sta_mac[6] = {0};
        (void)esp_wifi_get_mac(WIFI_IF_STA, sta_mac);

        uint32_t count = 0;
        while (true) {
            EventBits_t bits = xEventGroupGetBits(s_wifi_event_group);
            if ((bits & WIFI_GOTIP_BIT) == 0) {
                ESP_LOGW(TAG, "UDP heartbeat: lost IP, recreating socket...");
                break;
            }

            char payload[160];
            int len = snprintf(payload, sizeof(payload),
                               "{\"type\":\"hb\",\"count\":%lu,\"mac\":\"%02x:%02x:%02x:%02x:%02x:%02x\",\"uptime_ms\":%lu}",
                               (unsigned long)count,
                               sta_mac[0], sta_mac[1], sta_mac[2], sta_mac[3], sta_mac[4], sta_mac[5],
                               (unsigned long)(esp_log_timestamp()));
            if (len < 0) {
                ESP_LOGE(TAG, "UDP heartbeat: snprintf failed");
                vTaskDelay(pdMS_TO_TICKS(1000));
                continue;
            }

            int err = sendto(sock, payload, len, 0, (struct sockaddr *)&dest_addr, sizeof(dest_addr));
            if (err < 0) {
                ESP_LOGE(TAG, "UDP heartbeat: sendto() failed errno=%d", errno);
            } else {
                ESP_LOGD(TAG, "UDP heartbeat sent (%d bytes) -> %s:%d", err, UDP_SERVER_IP, UDP_SERVER_PORT);
            }
            count++;
            vTaskDelay(pdMS_TO_TICKS(HB_INTERVAL_MS));
        }

        shutdown(sock, 0);
        close(sock);
        vTaskDelay(pdMS_TO_TICKS(200));
    }
}

static void udp_send_json_event(int sock, const struct sockaddr_in *dest_addr, const char *json)
{
    /* 轻量封装：UDP 上报 JSON（无重试/无确认，强调低开销） */
    if (sock < 0 || dest_addr == NULL || json == NULL) {
        return;
    }
    (void)sendto(sock, json, (int)strlen(json), 0, (const struct sockaddr *)dest_addr, sizeof(*dest_addr));
}

static void wifi_event_handler(void *arg, esp_event_base_t event_base, int32_t event_id, void *event_data)
{
    /*
     * Wi-Fi/IP 事件处理：
     *   - CONNECTED: 记录 AP BSSID 到 s_csi_peer_mac（用于 CSI peer 过滤）
     *   - GOT_IP:    置位 WIFI_GOTIP_BIT，允许 UDP/CSI 任务开始工作
     *   - DISCONNECTED: 清 bit 并自动重连（限制重试次数），打印断开原因
     */
    // ── STA 事件 ──
    if (event_base == WIFI_EVENT && event_id == WIFI_EVENT_STA_DISCONNECTED) {
        const wifi_event_sta_disconnected_t *dis = (const wifi_event_sta_disconnected_t *)event_data;
        uint16_t reason = dis ? dis->reason : 0;
        xEventGroupClearBits(s_wifi_event_group, WIFI_GOTIP_BIT);
        if (s_retry_num < 10) {
            s_retry_num++;
            ESP_LOGW(TAG, "STA disconnected (reason=%u:%s), retry %d", (unsigned)reason, wifi_disconnect_reason_str(reason), s_retry_num);
            if (reason == WIFI_REASON_ASSOC_TOOMANY) {
                ESP_LOGW(TAG, "AP rejected association: too many stations.");
            }
            esp_wifi_connect();
        } else {
            ESP_LOGE(TAG, "STA reconnect failed (last reason=%u:%s)", (unsigned)reason, wifi_disconnect_reason_str(reason));
        }
    } else if (event_base == IP_EVENT && event_id == IP_EVENT_STA_GOT_IP) {
        ip_event_got_ip_t *event = (ip_event_got_ip_t *)event_data;
        s_retry_num = 0;
        ESP_LOGI(TAG, "STA got IP: " IPSTR, IP2STR(&event->ip_info.ip));
        xEventGroupSetBits(s_wifi_event_group, WIFI_GOTIP_BIT);
    } else if (event_base == WIFI_EVENT && event_id == WIFI_EVENT_STA_CONNECTED) {
        ESP_LOGI(TAG, "STA connected to %s, waiting DHCP...", WIFI_STA_SSID);
    // ── AP 事件：发送板连接/断开 ──
    } else if (event_base == WIFI_EVENT && event_id == WIFI_EVENT_AP_STACONNECTED) {
        const wifi_event_ap_staconnected_t *evt = (const wifi_event_ap_staconnected_t *)event_data;
        if (evt) {
            memcpy(s_csi_peer_mac, evt->mac, 6);
            s_csi_peer_mac_set = true;
            ESP_LOGI(TAG, "Sender connected to AP: " MACSTR " (set as CSI peer)", MAC2STR(s_csi_peer_mac));
        }
    } else if (event_base == WIFI_EVENT && event_id == WIFI_EVENT_AP_STADISCONNECTED) {
        const wifi_event_ap_stadisconnected_t *evt = (const wifi_event_ap_stadisconnected_t *)event_data;
        if (evt) {
            ESP_LOGW(TAG, "Sender disconnected: " MACSTR, MAC2STR(evt->mac));
            s_csi_peer_mac_set = false;
        }
    }
}

typedef struct {
    unsigned : 32; /**< reserved */
    unsigned : 32; /**< reserved */
    unsigned : 32; /**< reserved */
    unsigned : 32; /**< reserved */
    unsigned : 32; /**< reserved */
#if CONFIG_IDF_TARGET_ESP32S2
    unsigned : 32; /**< reserved */
#elif CONFIG_IDF_TARGET_ESP32S3 || CONFIG_IDF_TARGET_ESP32C3 || CONFIG_IDF_TARGET_ESP32C5 ||CONFIG_IDF_TARGET_ESP32C6
    unsigned : 16; /**< reserved */
    unsigned fft_gain : 8;
    unsigned agc_gain : 8;
    unsigned : 32; /**< reserved */
#endif
    unsigned : 32; /**< reserved */
#if CONFIG_IDF_TARGET_ESP32S2
    signed : 8;  /**< reserved */
    unsigned : 24; /**< reserved */
#elif CONFIG_IDF_TARGET_ESP32S3 || CONFIG_IDF_TARGET_ESP32C3 || CONFIG_IDF_TARGET_ESP32C5
    unsigned : 32; /**< reserved */
    unsigned : 32; /**< reserved */
    unsigned : 32; /**< reserved */
#endif
    unsigned : 32; /**< reserved */
} wifi_pkt_rx_ctrl_phy_t;

#if CONFIG_FORCE_GAIN
/**
 * @brief Enable/disable automatic fft gain control and set its value
 * @param[in] force_en true to disable automatic fft gain control
 * @param[in] force_value forced fft gain value
 */
extern void phy_fft_scale_force(bool force_en, uint8_t force_value);

/**
 * @brief Enable/disable automatic gain control and set its value
 * @param[in] force_en true to disable automatic gain control
 * @param[in] force_value forced gain value
 */
extern void phy_force_rx_gain(int force_en, int force_value);
#endif
static void wifi_init()
{
    /*
     * APSTA 模式初始化：
     *   - AP:  发送板直连，信道 11，1 连接，用于采集 CSI
     *   - STA: 连接手机热点，用于心跳/结果上传
     *   - CSI peer MAC 从 AP_STACONNECTED 事件学到（发送板的 MAC）
     */
    esp_err_t loop_ret = esp_event_loop_create_default();
    if (loop_ret != ESP_OK && loop_ret != ESP_ERR_INVALID_STATE) {
        ESP_ERROR_CHECK(loop_ret);
    }

    ESP_ERROR_CHECK(esp_netif_init());
    esp_netif_create_default_wifi_ap();
    esp_netif_create_default_wifi_sta();

    if (s_wifi_event_group == NULL) {
        s_wifi_event_group = xEventGroupCreate();
    }

    ESP_ERROR_CHECK(esp_event_handler_register(WIFI_EVENT, ESP_EVENT_ANY_ID, &wifi_event_handler, NULL));
    ESP_ERROR_CHECK(esp_event_handler_register(IP_EVENT, IP_EVENT_STA_GOT_IP, &wifi_event_handler, NULL));

    wifi_init_config_t cfg = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&cfg));

    // ── AP 配置（发送板直连）──
    wifi_config_t ap_config = {
        .ap = {
            .ssid = WIFI_AP_SSID,
            .ssid_len = (uint8_t)strlen(WIFI_AP_SSID),
            .password = WIFI_AP_PASS,
            .channel = WIFI_AP_CHANNEL,
            .max_connection = WIFI_AP_MAX_CONN,
            .authmode = WIFI_AUTH_WPA2_PSK,
        },
    };
    // ── STA 配置（连手机热点）──
    wifi_config_t sta_config = {
        .sta = {
            .ssid = WIFI_STA_SSID,
            .password = WIFI_STA_PASS,
            .threshold.authmode = WIFI_AUTH_OPEN,
            .pmf_cfg = { .capable = true, .required = false },
        },
    };

    ESP_LOGI(TAG, "APSTA mode: AP='%s' ch=%d, STA='%s'", WIFI_AP_SSID, WIFI_AP_CHANNEL, WIFI_STA_SSID);

    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_APSTA));
    ESP_ERROR_CHECK(esp_wifi_set_storage(WIFI_STORAGE_RAM));
    ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_AP, &ap_config));
    ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_STA, &sta_config));

#define USE_CUSTOM_STA_MAC 0
#if USE_CUSTOM_STA_MAC
    static const uint8_t custom_sta_mac[6] = {0x1a, 0x00, 0x00, 0x00, 0x00, 0x00};
    ESP_ERROR_CHECK(esp_wifi_set_mac(WIFI_IF_STA, custom_sta_mac));
#endif
    uint8_t sta_mac[6] = {0};
    ESP_ERROR_CHECK(esp_wifi_get_mac(WIFI_IF_STA, sta_mac));
    ESP_LOGI(TAG, "STA MAC: " MACSTR, MAC2STR(sta_mac));

    // CSI peer MAC 将在发送板连上 AP 时学到
    s_csi_peer_mac_set = false;

#if CONFIG_IDF_TARGET_ESP32C5
    ESP_ERROR_CHECK(esp_wifi_start());
    esp_wifi_set_band_mode(CONFIG_WIFI_BAND_MODE);
    wifi_protocols_t protocols = {
        .ghz_2g = CONFIG_WIFI_2G_PROTOCOL,
        .ghz_5g = CONFIG_WIFI_5G_PROTOCOL
    };
    ESP_ERROR_CHECK(esp_wifi_set_protocols(ESP_IF_WIFI_STA, &protocols));
    wifi_bandwidths_t bandwidth = {
        .ghz_2g = CONFIG_WIFI_2G_BANDWIDTHS,
        .ghz_5g = CONFIG_WIFI_5G_BANDWIDTHS
    };
    ESP_ERROR_CHECK(esp_wifi_set_bandwidths(ESP_IF_WIFI_STA, &bandwidth));
#elif CONFIG_IDF_TARGET_ESP32C6 || CONFIG_IDF_TARGET_ESP32C61
    ESP_ERROR_CHECK(esp_wifi_start());
    esp_wifi_set_band_mode(CONFIG_WIFI_BAND_MODE);
    wifi_protocols_t protocols = {
        .ghz_2g = CONFIG_WIFI_2G_PROTOCOL,
    };
    ESP_ERROR_CHECK(esp_wifi_set_protocols(ESP_IF_WIFI_STA, &protocols));
    wifi_bandwidths_t bandwidth = {
        .ghz_2g = CONFIG_WIFI_2G_BANDWIDTHS,
    };
    ESP_ERROR_CHECK(esp_wifi_set_bandwidths(ESP_IF_WIFI_STA, &bandwidth));
#else
    ESP_ERROR_CHECK(esp_wifi_set_bandwidth(ESP_IF_WIFI_STA, CONFIG_WIFI_BANDWIDTH));
    ESP_ERROR_CHECK(esp_wifi_set_bandwidth(ESP_IF_WIFI_AP, CONFIG_WIFI_BANDWIDTH));
    ESP_ERROR_CHECK(esp_wifi_start());
#endif

    ESP_ERROR_CHECK(esp_wifi_connect());

#if CONFIG_IDF_TARGET_ESP32 || CONFIG_IDF_TARGET_ESP32C3 || CONFIG_IDF_TARGET_ESP32S3
    ESP_ERROR_CHECK(esp_wifi_config_espnow_rate(ESP_IF_WIFI_STA, CONFIG_ESP_NOW_RATE));
#endif
    ESP_ERROR_CHECK(esp_wifi_set_ps(WIFI_PS_NONE));

    EventBits_t bits = xEventGroupWaitBits(s_wifi_event_group, WIFI_GOTIP_BIT, pdFALSE, pdFALSE, pdMS_TO_TICKS(15000));
    if ((bits & WIFI_GOTIP_BIT) == 0) {
        ESP_LOGW(TAG, "No IP within timeout; UDP may not work yet");
    }
}
#if CONFIG_IDF_TARGET_ESP32C5
static void wifi_esp_now_init(esp_now_peer_info_t peer)
{
    ESP_ERROR_CHECK(esp_now_init());
    ESP_ERROR_CHECK(esp_now_set_pmk((uint8_t *)"pmk1234567890123"));
    esp_now_rate_config_t rate_config = {
        .phymode = CONFIG_ESP_NOW_PHYMODE,
        .rate = CONFIG_ESP_NOW_RATE,//  WIFI_PHY_RATE_MCS0_LGI,
        .ersu = false,
        .dcm = false
    };
    ESP_ERROR_CHECK(esp_now_add_peer(&peer));
    ESP_ERROR_CHECK(esp_now_set_peer_rate_config(peer.peer_addr, &rate_config));

}
#endif

static void wifi_csi_rx_cb(void *ctx, wifi_csi_info_t *info)
{
    (void)ctx;

    /*
     * CSI 接收回调（Wi-Fi 驱动上下文）：
     *   只做轻量工作：校验 -> (可选)peer MAC 过滤 -> 拷贝 CSI -> 入队。
     *   重要：不要在这里做复杂计算或阻塞等待，否则可能影响 Wi-Fi 性能。
     */
    if (!info || !info->buf) {
        s_csi_invalid++;
        return;
    }

    s_csi_cb_count++;

    if (info->len > s_csi_max_info_len) {
        s_csi_max_info_len = info->len;
    }

    if (s_csi_queue == NULL) {
        s_csi_queue_missing++;
        return;
    }

    // Filter by peer MAC (AP BSSID) if available
    // Step 2-A: disable filtering for the first 5 minutes to learn who info->mac is.
    /*
     * 过滤策略（APSTA 模式）：
     *   - 前 CSI_FILTER_DISABLE_MS：不启用过滤，观察 info->mac 来源
     *   - 之后：仅保留匹配发送板 MAC 的 CSI 包；若发送板未连接则全部丢弃
     */
    bool filter_active = (esp_log_timestamp() >= s_csi_filter_disable_until_ms);

    // Track source MACs for debugging (best-effort, no locking)
    bool mac_accounted = false;
    for (uint8_t i = 0; i < s_csi_src_used; i++) {
        if (memcmp(s_csi_src_macs[i], info->mac, 6) == 0) {
            s_csi_src_counts[i]++;
            mac_accounted = true;
            break;
        }
    }
    if (!mac_accounted) {
        if (s_csi_src_used < CSI_DEBUG_MAC_SLOTS) {
            memcpy(s_csi_src_macs[s_csi_src_used], info->mac, 6);
            s_csi_src_counts[s_csi_src_used] = 1;
            s_csi_src_used++;
        } else {
            s_csi_src_other++;
        }
    }

    if (filter_active) {
        if (!s_csi_peer_mac_set || memcmp(info->mac, s_csi_peer_mac, 6) != 0) {
            s_csi_peer_filtered++;
            return;
        }
    }

    s_csi_rx_count++;

    csi_frame_t frame = {0};
    frame.local_ts_ms = esp_log_timestamp();
    frame.rssi = info->rx_ctrl.rssi;

    uint16_t copy_len = info->len;
    if (copy_len > CSI_BUF_MAX_LEN) {
        copy_len = CSI_BUF_MAX_LEN;
        s_csi_truncated++;
    }
    frame.len = copy_len;
    memcpy(frame.buf, info->buf, copy_len);

    if (xQueueSend(s_csi_queue, &frame, 0) == pdTRUE) {
        s_csi_enqueued++;
    } else {
        s_csi_dropped++;
    }
}

static float csi_packet_variance(const int8_t *buf, uint16_t len)
{
    /*
     * 简化特征：对单包 CSI 字节序列计算方差 var = E[x^2] - (E[x])^2。
     * 优点：计算量小，便于先跑通链路；缺点：信息损失大，仅适合原型/演示。
     */
    if (buf == NULL || len == 0) {
        return 0.0f;
    }

    int32_t sum = 0;
    int32_t sumsq = 0;
    for (uint16_t i = 0; i < len; i++) {
        int32_t v = (int32_t)buf[i];
        sum += v;
        sumsq += v * v;
    }

    const float n = (float)len;
    const float mean = (float)sum / n;
    const float mean_sq = (float)sumsq / n;
    float var = mean_sq - mean * mean;
    if (var < 0.0f) {
        var = 0.0f;
    }
    return var;
}

static const char *fsm_state_name(fsm_state_t s)
{
    switch (s) {
    case FSM_STILL: return "STILL";
    case FSM_MOTION: return "MOTION";
    case FSM_SUSPECT_FALL: return "SUSPECT_FALL";
    case FSM_CONFIRMED_FALL: return "CONFIRMED_FALL";
    default: return "UNKNOWN";
    }
}

static void csi_fsm_task(void *arg)
{
    (void)arg;

    /*
     * CSI 处理与状态机：
     *   - 消费 CSI 队列，计算每包方差并写入环形缓冲
     *   - 每 FEATURE_STEP_MS 计算过去 FEATURE_WINDOW_MS 的方差均值 feat
     *   - feat 阈值区分 STILL/MOTION；feat 跳变 delta 触发 SUSPECT_FALL
     *   - SUSPECT_FALL 后持续静止 FALL_STILL_CONFIRM_MS 确认 CONFIRMED_FALL
     *   - 状态变化时通过 UDP 上报 JSON 事件
     */

    // Wait until we have an IP address (so UDP event send will work)
    xEventGroupWaitBits(s_wifi_event_group, WIFI_GOTIP_BIT, pdFALSE, pdTRUE, portMAX_DELAY);

    struct sockaddr_in dest_addr = { 0 };
    dest_addr.sin_family = AF_INET;
    dest_addr.sin_port = htons(UDP_SERVER_PORT);
    dest_addr.sin_addr.s_addr = inet_addr(UDP_SERVER_IP);

    int sock = socket(AF_INET, SOCK_DGRAM, IPPROTO_IP);
    if (sock < 0) {
        ESP_LOGE(TAG, "FSM UDP socket() failed errno=%d", errno);
    }

    uint8_t sta_mac[6] = {0};
    (void)esp_wifi_get_mac(WIFI_IF_STA, sta_mac);
    uint32_t evt_seq = 0;

    // Circular buffer of per-packet variance for the last ~2 seconds
    memset(s_var_ring, 0, sizeof(s_var_ring));
    memset(s_ts_ring, 0, sizeof(s_ts_ring));
    uint16_t ring_head = 0;
    uint16_t ring_count = 0;

    float last_feat = 0.0f;
    fsm_state_t state = FSM_STILL;
    uint32_t still_since = 0;

    // Debug snapshots (printed once per second with CSI stats)
    float dbg_feat = 0.0f;
    float dbg_delta = 0.0f;
    uint16_t dbg_used = 0;
    int8_t dbg_rssi = 0;

    uint32_t last_step_ms = esp_log_timestamp();
    uint32_t last_stat_ms = last_step_ms;

    while (true) {
        csi_frame_t frame;
        // Drain queue quickly; keep loop responsive
        while (xQueueReceive(s_csi_queue, &frame, 0) == pdTRUE) {
            float v = csi_packet_variance(frame.buf, frame.len);
            s_var_ring[ring_head] = v;
            s_ts_ring[ring_head] = frame.local_ts_ms;
            dbg_rssi = frame.rssi;
            ring_head = (uint16_t)((ring_head + 1) % CSI_RING_SIZE);
            if (ring_count < CSI_RING_SIZE) {
                ring_count++;
            }
#if FALL_DETECT_ENABLE
            fall_detect_process_frame(frame.buf, frame.len, frame.local_ts_ms);
#endif
        }

        uint32_t now_ms = esp_log_timestamp();

        // Step every FEATURE_STEP_MS
        if ((now_ms - last_step_ms) >= FEATURE_STEP_MS) {
            last_step_ms = now_ms;

            // Compute feature: mean variance over last FEATURE_WINDOW_MS
            float feat = 0.0f;
            uint16_t used = 0;
            for (uint16_t i = 0; i < ring_count; i++) {
                uint16_t idx = (uint16_t)((ring_head + CSI_RING_SIZE - 1 - i) % CSI_RING_SIZE);
                uint32_t ts = s_ts_ring[idx];
                if ((now_ms - ts) > FEATURE_WINDOW_MS) {
                    break;
                }
                feat += s_var_ring[idx];
                used++;
            }
            if (used > 0) {
                feat /= (float)used;
            }

            float delta = feat - last_feat;
            if (delta < 0.0f) {
                delta = -delta;
            }

            // Snapshot current feature for debugging/threshold tuning
            dbg_feat = feat;
            dbg_delta = delta;
            dbg_used = used;

            // Base classifier for still/motion
            fsm_state_t base = state;
            if (feat >= FEAT_MOTION_TH) {
                base = FSM_MOTION;
            } else if (feat <= FEAT_STILL_TH) {
                base = FSM_STILL;
            }

            fsm_state_t next = state;

            // Trigger suspect fall on a strong feature jump
            if (delta >= FALL_DELTA_TH && state != FSM_CONFIRMED_FALL) {
                next = FSM_SUSPECT_FALL;
                still_since = 0;
            } else {
                switch (state) {
                case FSM_SUSPECT_FALL:
                    if (base == FSM_STILL) {
                        if (still_since == 0) {
                            still_since = now_ms;
                        }
                        if ((now_ms - still_since) >= FALL_STILL_CONFIRM_MS) {
                            next = FSM_CONFIRMED_FALL;
                        }
                    } else if (base == FSM_MOTION) {
                        next = FSM_MOTION; // cancel
                        still_since = 0;
                    }
                    // else: keep suspect
                    break;
                case FSM_CONFIRMED_FALL:
                    // stay confirmed until motion comes back
                    if (base == FSM_MOTION) {
                        next = FSM_MOTION;
                    }
                    break;
                case FSM_STILL:
                case FSM_MOTION:
                default:
                    next = base;
                    break;
                }
            }

            if (next != state) {
                evt_seq++;
                char json[320];
                int n = snprintf(json, sizeof(json),
                                 "{\"type\":\"csi_evt\",\"seq\":%lu,\"mac\":\"%02x:%02x:%02x:%02x:%02x:%02x\",\"state\":\"%s\",\"prev\":\"%s\",\"feat\":%.2f,\"delta\":%.2f,\"samples\":%u,\"win_ms\":%d,\"step_ms\":%d,\"t_ms\":%lu}",
                                 (unsigned long)evt_seq,
                                 sta_mac[0], sta_mac[1], sta_mac[2], sta_mac[3], sta_mac[4], sta_mac[5],
                                 fsm_state_name(next), fsm_state_name(state),
                                 (double)feat, (double)delta,
                                 (unsigned)used,
                                 (int)FEATURE_WINDOW_MS, (int)FEATURE_STEP_MS,
                                 (unsigned long)now_ms);
                if (n > 0) {
                    ESP_LOGI(TAG, "FSM %s -> %s (feat=%.2f delta=%.2f used=%u)",
                             fsm_state_name(state), fsm_state_name(next), (double)feat, (double)delta, (unsigned)used);
                    if (sock >= 0) {
                        udp_send_json_event(sock, &dest_addr, json);
                    }
                }
                state = next;
            }

            last_feat = feat;
        }

        // Print stats once per second
        if ((now_ms - last_stat_ms) >= 1000) {
            last_stat_ms = now_ms;
            UBaseType_t q_waiting = (s_csi_queue != NULL) ? uxQueueMessagesWaiting(s_csi_queue) : 0;
                ESP_LOGI(TAG, "CSI stats: cb=%lu rx=%lu enq=%lu drop=%lu trunc=%lu maxlen=%u filt=%lu inv=%lu qmiss=%lu q=%lu state=%s fall=%s",
                     (unsigned long)s_csi_cb_count,
                     (unsigned long)s_csi_rx_count,
                     (unsigned long)s_csi_enqueued,
                     (unsigned long)s_csi_dropped,
                     (unsigned long)s_csi_truncated,
                         (unsigned)s_csi_max_info_len,
                     (unsigned long)s_csi_peer_filtered,
                     (unsigned long)s_csi_invalid,
                     (unsigned long)s_csi_queue_missing,
                     (unsigned long)q_waiting,
                     fsm_state_name(state),
                     fall_detect_state_str());

            ESP_LOGI(TAG, "FSM feat=%.2f delta=%.2f used=%u last_rssi=%d",
                     (double)dbg_feat, (double)dbg_delta, (unsigned)dbg_used, (int)dbg_rssi);

            // Print observed CSI source MACs (best-effort)
            char mac_line[220];
            int off = snprintf(mac_line, sizeof(mac_line), "CSI src macs:");
            for (uint8_t i = 0; i < s_csi_src_used && off > 0 && off < (int)sizeof(mac_line); i++) {
                off += snprintf(mac_line + off, sizeof(mac_line) - (size_t)off,
                               " " MACSTR "(%lu)",
                               MAC2STR(s_csi_src_macs[i]),
                               (unsigned long)s_csi_src_counts[i]);
            }
            if (s_csi_src_other > 0 && off > 0 && off < (int)sizeof(mac_line)) {
                (void)snprintf(mac_line + off, sizeof(mac_line) - (size_t)off, " other(%lu)", (unsigned long)s_csi_src_other);
            }
            ESP_LOGI(TAG, "%s", mac_line);

            if (now_ms < s_csi_filter_disable_until_ms) {
                ESP_LOGI(TAG, "CSI peer filter disabled (%lu ms left)",
                         (unsigned long)(s_csi_filter_disable_until_ms - now_ms));
            } else {
                ESP_LOGI(TAG, "CSI peer filter active (AP BSSID=%s)", s_csi_peer_mac_set ? "set" : "unset");
            }
        }

        // Always yield at least 1 tick
        TickType_t d = pdMS_TO_TICKS(10);
        if (d == 0) d = 1;
#if FALL_DETECT_ENABLE
        fall_detect_tick();
#endif
        vTaskDelay(d);
    }
}

static void wifi_csi_init()
{
    /*
     * CSI 初始化：
     *   - 开启 promiscuous
     *   - 设置 CSI 配置（不同芯片目标 wifi_csi_config_t 字段不同）
     *   - 注册 CSI 回调并启用 CSI
     */
    ESP_ERROR_CHECK(esp_wifi_set_promiscuous(true));

    /**< default config */
#if CONFIG_IDF_TARGET_ESP32C5
    wifi_csi_config_t csi_config = {
        .enable                   = true,
        .acquire_csi_legacy       = false,
        .acquire_csi_force_lltf   = CSI_FORCE_LLTF,
        .acquire_csi_ht20         = true,
        .acquire_csi_ht40         = true,
        .acquire_csi_vht          = false,
        .acquire_csi_su           = false,
        .acquire_csi_mu           = false,
        .acquire_csi_dcm          = false,
        .acquire_csi_beamformed   = false,
        .acquire_csi_he_stbc_mode = 2,
        .val_scale_cfg            = 0,
        .dump_ack_en              = false,
        .reserved                 = false
    };
#elif CONFIG_IDF_TARGET_ESP32C6
    wifi_csi_config_t csi_config = {
        .enable                 = true,
        .acquire_csi_legacy     = false,
        .acquire_csi_ht20       = true,
        .acquire_csi_ht40       = true,
        .acquire_csi_su         = true,
        .acquire_csi_mu         = true,
        .acquire_csi_dcm        = true,
        .acquire_csi_beamformed = true,
        .acquire_csi_he_stbc    = 2,
        .val_scale_cfg          = false,
        .dump_ack_en            = false,
        .reserved               = false
    };
#else
    wifi_csi_config_t csi_config = {
        .lltf_en           = false,       // 只保留 HT-LTF，消除交替
        .htltf_en          = true,
        .stbc_htltf2_en    = false,
        .ltf_merge_en      = false,
        .channel_filter_en = true,
        .manu_scale        = false,
        .shift             = false,
    };
#endif
    ESP_ERROR_CHECK(esp_wifi_set_csi_config(&csi_config));
    ESP_ERROR_CHECK(esp_wifi_set_csi_rx_cb(wifi_csi_rx_cb, NULL));
    ESP_ERROR_CHECK(esp_wifi_set_csi(true));
}

#if FALL_DETECT_ENABLE
/* 跌倒事件回调 → UDP 云上报（csi_evt 格式） */
static void fall_event_handler(int event_type)
{
    if (event_type != 0) return;  /* 只上报确认事件 */

    struct sockaddr_in dest = { 0 };
    dest.sin_family = AF_INET;
    dest.sin_port = htons(UDP_SERVER_PORT);
    dest.sin_addr.s_addr = inet_addr(UDP_SERVER_IP);

    int sock = socket(AF_INET, SOCK_DGRAM, IPPROTO_IP);
    if (sock < 0) return;

    uint8_t mac[6]; esp_wifi_get_mac(WIFI_IF_STA, mac);
    char json[256];
    snprintf(json, sizeof(json),
        "{\"type\":\"csi_evt\",\"mac\":\"%02x:%02x:%02x:%02x:%02x:%02x\","
        "\"note\":\"fall\"}",
        mac[0],mac[1],mac[2],mac[3],mac[4],mac[5]);
    sendto(sock, json, (int)strlen(json), 0, (struct sockaddr *)&dest, sizeof(dest));
    close(sock);
    ESP_LOGI(TAG, "Fall event sent: %s", json);
}
#endif

void app_main()
{
    /*
     * 启动顺序：
     *   NVS -> Wi-Fi STA -> UDP 心跳任务 -> 可选)ESP-NOCSI 队列/FSM 任务 -> (W -> CSI 启动。
     */
    /**
     * @brief Initialize NVS
     */
    esp_err_t ret = nvs_flash_init();
    if (ret == ESP_ERR_NVS_NO_FREE_PAGES || ret == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_ERROR_CHECK(nvs_flash_erase());
        ret = nvs_flash_init();
    }
    ESP_ERROR_CHECK(ret);

    /**
     * @brief Initialize Wi-Fi
     */
    s_csi_filter_disable_until_ms = esp_log_timestamp() + CSI_FILTER_DISABLE_MS;
    wifi_init();

    /* UDP heartbeat (for quick connectivity verification) */
    xTaskCreate(udp_heartbeat_task, "udp_hb", 4096, NULL, 5, NULL);

    /* CSI processing queue */
    if (s_csi_queue == NULL) {
        s_csi_queue = xQueueCreate(CSI_QUEUE_LEN, sizeof(csi_frame_t));
    }

#if FALL_DETECT_ENABLE
    fall_detect_init();
    /* 注册云上报回调：跌倒确认时发送 UDP 事件 */
    fall_detect_set_event_callback(fall_event_handler);
    ESP_LOGI(TAG, "Fall detection enabled (WS2812 GPIO48)");
#endif

#if CSI_RAW_DUMP_MODE
    /*
     * 原始数据采集模式：停用 FSM，改用二进制 CSI 透传
     * csi_raw_sender_task: 队列 → 二进制打包 → UDP sendto
     */
    ESP_LOGI(TAG, "Running in RAW CSI DUMP mode");
    xTaskCreate(csi_raw_sender_task, "csi_raw", 4096, NULL, 6, NULL);
#else
    /*
     * 推理模式：运行特征提取 + 状态机/模型推理
     */
    ESP_LOGI(TAG, "Running in INFERENCE mode");
    xTaskCreate(csi_fsm_task, "csi_fsm", 6144, NULL, 6, NULL);
#endif

    /**
     * @brief Initialize ESP-NOW
     *        ESP-NOW protocol see: https://docs.espressif.com/projects/esp-idf/en/latest/esp32/api-reference/network/esp_now.html
     */
#if CONFIG_IDF_TARGET_ESP32C5
    esp_now_peer_info_t peer = {
        .channel   = 0,
        .ifidx     = WIFI_IF_STA,
        .encrypt   = false,
        .peer_addr = {0xff, 0xff, 0xff, 0xff, 0xff, 0xff},
    };

    wifi_esp_now_init(peer);
#endif
    wifi_csi_init();
}
