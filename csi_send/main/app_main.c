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
#include <unistd.h>

#include "freertos/FreeRTOS.h"
#include "freertos/event_groups.h"
#include "freertos/task.h"

#include "nvs_flash.h"

#include "esp_mac.h"
#include "esp_log.h"
#include "esp_wifi.h"
#include "esp_netif.h"
#include "esp_event.h"
#include "esp_err.h"

#include "lwip/sockets.h"
#include "lwip/inet.h"

// UDP sender configuration
#define WIFI_SSID       "csi_recv"
#define WIFI_PASS       "12345678"
#define UDP_DEST_IP     "192.168.4.1"
#define UDP_DEST_PORT   5555
#define SEND_HZ         100
#define PAYLOAD_SIZE    200
#define ENOMEM_BACKOFF_MS 2    /* pause when TX buffer full */

#define WIFI_CONNECTED_BIT BIT0

static const char *TAG = "udp_sender";
static EventGroupHandle_t s_wifi_event_group;

static void wifi_event_handler(void *arg, esp_event_base_t event_base, int32_t event_id, void *event_data)
{
    if (event_base == WIFI_EVENT && event_id == WIFI_EVENT_STA_START) {
        ESP_ERROR_CHECK(esp_wifi_connect());
    } else if (event_base == WIFI_EVENT && event_id == WIFI_EVENT_STA_DISCONNECTED) {
        ESP_LOGW(TAG, "Wi-Fi disconnected, retrying");
        ESP_ERROR_CHECK(esp_wifi_connect());
    } else if (event_base == IP_EVENT && event_id == IP_EVENT_STA_GOT_IP) {
        xEventGroupSetBits(s_wifi_event_group, WIFI_CONNECTED_BIT);
    }
}

static void wifi_init()
{
    s_wifi_event_group = xEventGroupCreate();
    ESP_ERROR_CHECK(esp_event_loop_create_default());

    ESP_ERROR_CHECK(esp_netif_init());
    esp_netif_create_default_wifi_sta();
    wifi_init_config_t cfg = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&cfg));

    /* Fix TX rate to MCS0 to prevent CSI amplitude jumps from rate adaptation */
    esp_wifi_config_80211_tx_rate(ESP_IF_WIFI_STA, WIFI_PHY_RATE_MCS0_LGI);

    ESP_ERROR_CHECK(esp_event_handler_register(WIFI_EVENT, ESP_EVENT_ANY_ID, &wifi_event_handler, NULL));
    ESP_ERROR_CHECK(esp_event_handler_register(IP_EVENT, IP_EVENT_STA_GOT_IP, &wifi_event_handler, NULL));

    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
    ESP_ERROR_CHECK(esp_wifi_set_storage(WIFI_STORAGE_RAM));

    wifi_config_t wifi_config = {
        .sta = {
            .ssid = WIFI_SSID,
            .password = WIFI_PASS,
            .threshold.authmode = WIFI_AUTH_WPA2_PSK,
            .pmf_cfg = {
                .capable = true,
                .required = false,
            },
        },
    };
    ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_STA, &wifi_config));
    ESP_ERROR_CHECK(esp_wifi_start());
    ESP_ERROR_CHECK(esp_wifi_set_ps(WIFI_PS_NONE));
}

void app_main()
{
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
    wifi_init();

    ESP_LOGI(TAG, "Waiting for IP (GOT_IP)...");
    xEventGroupWaitBits(s_wifi_event_group, WIFI_CONNECTED_BIT, pdFALSE, pdTRUE, portMAX_DELAY);

    int sock = socket(AF_INET, SOCK_DGRAM, IPPROTO_IP);
    if (sock < 0) {
        ESP_LOGE(TAG, "Unable to create socket: %d", errno);
        return;
    }

    struct sockaddr_in dest_addr = {0};
    dest_addr.sin_family = AF_INET;
    dest_addr.sin_port = htons(UDP_DEST_PORT);
    dest_addr.sin_addr.s_addr = inet_addr(UDP_DEST_IP);

    uint8_t payload[PAYLOAD_SIZE] = {0};
    uint32_t sent_total = 0;
    uint32_t last_ms = xTaskGetTickCount() * portTICK_PERIOD_MS;
    const TickType_t period_ticks = pdMS_TO_TICKS(1000 / SEND_HZ);
    TickType_t last_wake = xTaskGetTickCount();

    ESP_LOGI(TAG, "UDP sender started: %s:%d, payload=%d bytes, rate=%d Hz",
             UDP_DEST_IP, UDP_DEST_PORT, PAYLOAD_SIZE, SEND_HZ);

    uint32_t enomem_count = 0;
    for (;;) {
        int err = sendto(sock, payload, sizeof(payload), 0, (struct sockaddr *)&dest_addr, sizeof(dest_addr));
        if (err < 0) {
            if (errno == ENOMEM) {
                enomem_count++;
                vTaskDelay(pdMS_TO_TICKS(ENOMEM_BACKOFF_MS)); /* let TX drain */
            } else {
                ESP_LOGW(TAG, "sendto failed: %d", errno);
            }
        } else {
            sent_total++;
        }

        uint32_t now_ms = xTaskGetTickCount() * portTICK_PERIOD_MS;
        if (now_ms - last_ms >= 1000) {
            ESP_LOGI(TAG, "tx_rate=%lu pkt/s, enomem=%lu", (unsigned long)sent_total, (unsigned long)enomem_count);
            sent_total = 0;
            enomem_count = 0;
            last_ms = now_ms;
        }

        vTaskDelayUntil(&last_wake, period_ticks);
    }
}
