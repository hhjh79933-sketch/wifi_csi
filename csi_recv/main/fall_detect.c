/*
 * fall_detect.c — 阈值跌倒检测 + WS2812 RGB LED (GPIO48, RMT)
 * 对应 Python: tools/threshold_detect_v3.py
 */
#include "fall_detect.h"
#include <string.h>
#include <math.h>
#include "driver/rmt_tx.h"
#include "esp_log.h"

static const char *TAG_FD = "fall_detect";

/* ── 参数 ── */
#define FALL_WIN           48
#define FALL_STEP          8
#define FALL_THRESHOLD     1.08f
#define FALL_SILENCE_SEC   2.5f
#define FALL_CONFIRM_SEC   3.0f   /* 疑似后确认时长 */
#define FALL_MAX_DENSE     8
#define FALL_N_SC          64
#define FALL_RING_SIZE     256
#define WS2812_GPIO        48

/* ── 状态 ── */
typedef enum { FS_IDLE=0, FS_STILL, FS_MOTION, FS_SUSPECT, FS_FALL } fall_state_t;

/* ── 状态变量 ── */
typedef enum { CLR_OFF=0, CLR_GREEN, CLR_ORANGE, CLR_RED } led_color_t;
typedef enum { BLINK_STEADY=0, BLINK_SLOW, BLINK_FAST } blink_t;

static float  s_var_ring[FALL_RING_SIZE];
static uint32_t s_ts_ring[FALL_RING_SIZE];
static uint16_t s_ring_head, s_ring_count, s_frame_count;
static fall_state_t s_state = FS_IDLE;
static led_color_t s_led_color = CLR_OFF;
static blink_t s_led_blink = BLINK_STEADY;
static bool s_led_on = true;

static rmt_channel_handle_t s_rmt_chan;
static rmt_encoder_handle_t s_rmt_enc;
static rmt_transmit_config_t s_tx_cfg;

static bool s_in_spike;
static int  s_spike_count, s_pre_silence, s_post_silence;
static int  s_spike_pre_snapshot, s_silence_win;
static float s_baseline = -1.0f;
static uint32_t s_suspect_ms = 0;    /* 进入疑似跌倒的时间 */
static fall_event_cb_t s_event_cb = NULL;

static void ws2812_send(uint8_t r, uint8_t g, uint8_t b);
static void led_update(void);

/* ═════════════════════════ WS2812 RMT ═══════════════════════ */
#define RMT_CLK_DIV  4
#define T0H_TICKS  ((400+25)/50)   /* 8 */
#define T0L_TICKS  ((850+25)/50)   /* 17 */
#define T1H_TICKS  ((800+25)/50)   /* 16 */
#define T1L_TICKS  ((450+25)/50)   /* 9 */

typedef struct {
    rmt_encoder_t base;
    rmt_encoder_t *copy_enc;
    rmt_symbol_word_t bit0, bit1;
} ws2812_enc_t;

static size_t ws2812_encode(rmt_encoder_t *enc, rmt_channel_handle_t ch,
    const void *data, size_t sz, rmt_encode_state_t *st)
{
    ws2812_enc_t *e = __containerof(enc, ws2812_enc_t, base);
    const uint8_t *b = (const uint8_t *)data;
    for (size_t i = 0; i < sz; i++)
        for (int bit = 7; bit >= 0; bit--) {
            rmt_symbol_word_t sym = (b[i] >> bit) & 1 ? e->bit1 : e->bit0;
            e->copy_enc->encode(e->copy_enc, ch, &sym, sizeof(sym), st);
        }
    *st = RMT_ENCODING_COMPLETE;
    return sz;
}
static esp_err_t ws2812_del(rmt_encoder_t *enc) {
    ws2812_enc_t *e = __containerof(enc, ws2812_enc_t, base);
    e->copy_enc->del(e->copy_enc); free(e); return ESP_OK;
}
static esp_err_t ws2812_reset(rmt_encoder_t *enc) {
    ws2812_enc_t *e = __containerof(enc, ws2812_enc_t, base);
    return e->copy_enc->reset(e->copy_enc);
}

static void ws2812_init(void)
{
    rmt_tx_channel_config_t cfg = {
        .gpio_num = WS2812_GPIO, .clk_src = RMT_CLK_SRC_DEFAULT,
        .resolution_hz = 80000000 / RMT_CLK_DIV,
        .mem_block_symbols = 64, .trans_queue_depth = 4,
    };
    rmt_new_tx_channel(&cfg, &s_rmt_chan);
    rmt_enable(s_rmt_chan);

    ws2812_enc_t *e = calloc(1, sizeof(*e));
    e->base.encode = ws2812_encode; e->base.del = ws2812_del;
    e->base.reset = ws2812_reset;
    e->bit0 = (rmt_symbol_word_t){{T0H_TICKS,1,T0L_TICKS,0}};
    e->bit1 = (rmt_symbol_word_t){{T1H_TICKS,1,T1L_TICKS,0}};
    rmt_new_copy_encoder(&(rmt_copy_encoder_config_t){}, &e->copy_enc);
    s_rmt_enc = &e->base;
    s_tx_cfg = (rmt_transmit_config_t){.loop_count=0, .flags.eot_level=0};
}

static void ws2812_send(uint8_t r, uint8_t g, uint8_t b)
{
    if (!s_rmt_chan || !s_rmt_enc) return;
    uint8_t d[3] = {g, r, b};  /* GRB order */
    rmt_transmit(s_rmt_chan, s_rmt_enc, d, 3, &s_tx_cfg);
    /* 不阻塞等待——让 RMT 硬件后台完成，避免和 WiFi 争抢总线 */
}

/* ═══════════════════════ LED（无定时器） ═══════════════════════ */
static uint32_t s_blink_interval_ms = 0;  /* 0=常亮 */
static uint32_t s_last_toggle_ms = 0;

static void led_update(void)
{
    if (s_led_color == CLR_OFF) { ws2812_send(0,0,0); return; }
    if (s_led_blink && !s_led_on) { ws2812_send(0,0,0); return; }  /* 灭相位 */
    switch (s_led_color) {
    case CLR_GREEN:  ws2812_send(0,255,0);   break;
    case CLR_ORANGE: ws2812_send(255,165,0); break;
    case CLR_RED:    ws2812_send(255,0,0);   break;
    default: break;
    }
}

static void led_set(led_color_t c, blink_t b)
{
    s_led_color = c; s_led_blink = b;
    s_led_on = true;
    s_last_toggle_ms = esp_log_timestamp();
    s_blink_interval_ms = (b == BLINK_SLOW) ? 500 : (b == BLINK_FAST ? 125 : 0);
    led_update();
}

/* 在主循环中调用——不在定时器/中断上下文 */
void fall_detect_tick(void)
{
    if (s_blink_interval_ms == 0) return;
    uint32_t now = esp_log_timestamp();
    if ((now - s_last_toggle_ms) >= s_blink_interval_ms) {
        s_last_toggle_ms = now;
        s_led_on = !s_led_on;
        led_update();
    }
}

/* ═══════════════════ CSI 处理 ═══════════════════ */
static float compute_frame_variance(const int8_t *buf, uint16_t len)
{
    if (!buf || len < 128) return 0.0f;
    int n = FALL_N_SC; float amp[64], sum = 0.0f;
    for (int i = 0; i < n; i++) {
        float I = (float)(int8_t)buf[i*2], Q = (float)(int8_t)buf[i*2+1];
        amp[i] = sqrtf(I*I + Q*Q); sum += amp[i];
    }
    float mean = sum / (float)n; if (mean < 1e-8f) return 0.0f;
    float var = 0.0f;
    for (int i = 0; i < n; i++) { float d = amp[i]/mean - 1.0f; var += d*d; }
    return var / (float)n;
}

static void run_detection(void)
{
    if (s_ring_count < FALL_WIN) return;
    float ws = 0.0f;
    for (int i = 0; i < FALL_WIN; i++)
        ws += s_var_ring[(s_ring_head+FALL_RING_SIZE-1-i)%FALL_RING_SIZE];
    float wm = ws / (float)FALL_WIN;

    if (s_baseline < 0 && s_ring_count >= FALL_WIN + 10) {
        float bs = 0.0f;
        for (int i = 0; i < 10; i++)
            bs += s_var_ring[(s_ring_head+FALL_RING_SIZE-1-i)%FALL_RING_SIZE];
        s_baseline = bs / 10.0f;
    }
    if (s_baseline < 0) return;
    float th = s_baseline * FALL_THRESHOLD;

    if (wm > th) {
        if (!s_in_spike) { s_spike_pre_snapshot=s_pre_silence; s_in_spike=true; s_spike_count=1; s_post_silence=0; }
        else s_spike_count++;
        s_pre_silence = 0;
    } else {
        s_pre_silence++;
        if (s_in_spike) {
            s_post_silence++;
            if (s_spike_count > FALL_MAX_DENSE) { s_in_spike=false; s_spike_count=0; s_post_silence=0; }
            else if (s_post_silence >= s_silence_win) {
                if (s_spike_pre_snapshot >= s_silence_win) {
                    if (s_state != FS_SUSPECT && s_state != FS_FALL) {
                        s_state = FS_SUSPECT;
                        s_suspect_ms = esp_log_timestamp();
                        led_set(CLR_RED, BLINK_STEADY);  /* 红灯常亮=疑似 */
                        ESP_LOGW(TAG_FD, ">>> SUSPECT FALL (confirming %ds...) <<<", (int)FALL_CONFIRM_SEC);
                        if (s_event_cb) s_event_cb(1);   /* 疑似事件 */
                    }
                }
                s_in_spike=false; s_spike_count=0; s_post_silence=0;
            }
        }
    }
}

/* ═══════════════════ Public API ═══════════════════ */
void fall_detect_init(void)
{
    s_silence_win = (int)(FALL_SILENCE_SEC * 92.0f / (float)FALL_STEP);
    if (s_silence_win < 1) s_silence_win = 1;
    memset(s_var_ring, 0, sizeof(s_var_ring));
    memset(s_ts_ring, 0, sizeof(s_ts_ring));
    s_ring_head = s_ring_count = s_frame_count = 0;
    s_state = FS_IDLE; s_in_spike = false;
    s_spike_count = s_pre_silence = s_post_silence = 0;
    s_baseline = -1.0f;
    ws2812_init();
    led_set(CLR_OFF, BLINK_STEADY);
    ESP_LOGI(TAG_FD, "Fall detect OK (WS2812 GPIO%d)", WS2812_GPIO);
}

void fall_detect_process_frame(const int8_t *csi_buf, uint16_t len, uint32_t ts_ms)
{
    if (!csi_buf || len < 128) return;
    float var = compute_frame_variance(csi_buf, 128);
    s_var_ring[s_ring_head] = var;
    s_ts_ring[s_ring_head] = ts_ms;
    s_ring_head = (s_ring_head + 1) % FALL_RING_SIZE;
    if (s_ring_count < FALL_RING_SIZE) s_ring_count++;
    s_frame_count++;
    if ((s_frame_count % FALL_STEP) == 0) run_detection();

    /* ── 10s 确认计时 ── */
    if (s_state == FS_SUSPECT) {
        uint32_t elapsed = ts_ms - s_suspect_ms;
        if (!s_in_spike && s_pre_silence > s_silence_win * 4) {
            /* 持续静默 > 10s → 确认跌倒 */
            if (elapsed >= (uint32_t)(FALL_CONFIRM_SEC * 1000)) {
                s_state = FS_FALL;
                led_set(CLR_RED, BLINK_FAST);  /* 红灯快闪=确认 */
                ESP_LOGW(TAG_FD, ">>> FALL CONFIRMED <<<");
                if (s_event_cb) s_event_cb(0);  /* 云上报 */
                /* 上报后回到静止 */
                s_state = FS_STILL;
                led_set(CLR_GREEN, BLINK_STEADY);
                ESP_LOGI(TAG_FD, "Reset to STILL (event sent)");
            }
        } else if (s_in_spike && s_spike_count > FALL_MAX_DENSE) {
            /* 疑似期间出现运动 → 取消 */
            s_state = FS_MOTION;
            led_set(CLR_ORANGE, BLINK_SLOW);
            ESP_LOGI(TAG_FD, "Suspect fall cancelled (motion resumed)");
            if (s_event_cb) s_event_cb(2);  /* 恢复事件 */
        }
    }

    if (s_state == FS_MOTION && !s_in_spike && s_pre_silence > s_silence_win*2)
    { s_state = FS_STILL; led_set(CLR_GREEN, BLINK_STEADY); }
    if (s_state == FS_IDLE && s_ring_count >= FALL_WIN)
    { s_state = FS_STILL; led_set(CLR_GREEN, BLINK_STEADY); }
    if (s_in_spike && s_spike_count > FALL_MAX_DENSE) {
        if (s_state != FS_MOTION) { s_state = FS_MOTION; led_set(CLR_ORANGE, BLINK_SLOW); }
    }
    /* 跌倒恢复：长时间静默 → 回到静止 */
    if (s_state == FS_FALL && !s_in_spike && s_pre_silence > s_silence_win * 4) {
        s_state = FS_STILL; led_set(CLR_GREEN, BLINK_STEADY);
        ESP_LOGI(TAG_FD, "Fall state cleared (long silence)");
    }
}

void fall_detect_set_event_callback(fall_event_cb_t cb) { s_event_cb = cb; }

const char *fall_detect_state_str(void)
{
    switch (s_state) {
    case FS_IDLE: return "IDLE"; case FS_STILL: return "STILL";
    case FS_MOTION: return "MOTION"; case FS_SUSPECT: return "SUSPECT";
    case FS_FALL: return "FALL";
    default: return "UNKNOWN";
    }
}
