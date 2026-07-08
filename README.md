# 🛡️ WiFi-CSI 人体感知与跌倒检测系统

> 基于 ESP32-S3 的 Wi-Fi CSI（信道状态信息）实时跌倒检测系统 —— 边缘推理 + 云端协同 + 移动端告警。

[![ESP-IDF v5.3.4](https://img.shields.io/badge/ESP--IDF-v5.3.4-blue)](https://github.com/espressif/esp-idf)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-green)](https://www.python.org/)
[![Android](https://img.shields.io/badge/Android-7.0%2B-brightgreen)](https://developer.android.com/)
[![License MIT](https://img.shields.io/badge/License-MIT-yellow)](LICENSE)

---

## 📖 目录

- [系统架构](#-系统架构)
- [项目结构](#-项目结构)
- [功能特性](#-功能特性)
- [硬件清单](#-硬件清单)
- [快速开始](#-快速开始)
- [子模块说明](#-子模块说明)
  - [csi_send — CSI 发送板固件](#csi_send--csi-发送板固件)
  - [csi_recv — CSI 接收板固件](#csi_recv--csi-接收板固件)
  - [esp-admin — Web 管理后台](#esp-admin--web-管理后台)
  - [mobile-backend — 移动端 API 服务](#mobile-backend--移动端-api-服务)
  - [android — Android 客户端](#android--android-客户端)
- [算法原理](#-算法原理)
- [ESP32-S3 CSI 硬件局限](#-esp32-s3-csi-硬件局限)
- [许可证](#-许可证)

---

## 🏗️ 系统架构

```mermaid
flowchart TB
    subgraph 感知层
        TX[发送板 ESP32-S3<br/>纯发包机<br/>MCS0 固定速率<br/>100Hz UDP 发包]
        RX[接收板 ESP32-S3<br/>APSTA 模式<br/>CSI 采集与解析<br/>滑窗方差+阈值判定<br/>WS2812B RGB LED]
    end

    subgraph 云端层
        INGEST[UDP 数据接收<br/>flask ingest udp<br/>端口 :9000]
        ADMIN[Web 管理后台<br/>Flask + SQLAlchemy<br/>设备/区域/NFC 管理]
        API[移动端 API<br/>Flask + JWT<br/>用户认证+告警推送]
        DB[(MySQL / SQLite<br/>esp_admin)]
    end

    subgraph 用户层
        APP[Android 客户端<br/>告警查看+状态管理<br/>NFC 区域绑定]
    end

    TX -->|UDP 100Hz| RX
    RX -->|UDP JSON 事件| INGEST
    INGEST --> DB
    ADMIN --> DB
    API --> DB
    APP -->|REST API| API
    APP -->|NFC 刷卡| RX
```

---

## 📁 项目结构

```
wifi_csi/
├── README.md                       # ← 本文件（顶层说明）
├── LICENSE                         # MIT 许可证
├── .gitignore                      # 顶层 Git 忽略规则
├── database_structure.sql          # MySQL 数据库结构导出
│
├── csi_send/                       # ① ESP32-S3 CSI 发送板固件
│   ├── main/app_main.c             #    主程序：WiFi STA + UDP 发包
│   ├── CMakeLists.txt
│   ├── sdkconfig.defaults
│   └── README.md
│
├── csi_recv/                       # ② ESP32-S3 CSI 接收板固件（核心）
│   ├── main/
│   │   ├── app_main.c              #    主程序：APSTA + CSI 采集 + UDP 上报
│   │   ├── fall_detect.c           #    跌倒检测算法 + WS2812 LED 驱动
│   │   └── fall_detect.h
│   ├── tools/                      #    Python 分析 & 训练工具
│   │   ├── threshold_detect_v3.py  #    阈值检测算法（PC 端验证）
│   │   ├── train_cnn.py            #    1D-CNN 训练脚本
│   │   ├── full_pipeline.py        #    信号处理全流程可视化
│   │   ├── plot_one.py             #    单文件绘图工具
│   │   └── serial_capture.py       #    串口 CSI 数据采集
│   ├── server/
│   │   └── udp_ingest.py           #    UDP 数据接收脚本
│   ├── data/                       #    实验数据集（寝室环境）
│   │   ├── still.txt               #    静止场景（60s）
│   │   ├── motion.txt              #    运动场景（60s）
│   │   ├── fall_01.txt ~ fall_10.txt  # 跌倒场景（10条）
│   │   └── full_pipeline.png       #    信号处理可视化图
│   ├── test/                       #    测试数据集
│   │   └── test_1.txt ~ test_4.txt
│   ├── models/
│   │   └── fall_cnn_v2.pth         #    训练好的 CNN 模型
│   ├── CMakeLists.txt
│   ├── sdkconfig.defaults
│   └── README.md
│
├── esp-admin/                      # ③ Web 管理后台
│   ├── wsgi.py                     #    WSGI 入口
│   ├── app/
│   │   ├── __init__.py             #    应用工厂
│   │   ├── config.py               #    配置加载
│   │   ├── extensions.py           #    Flask 扩展
│   │   ├── blueprints/             #    路由蓝图
│   │   │   ├── admin/routes.py     #    管理页面
│   │   │   ├── api/routes.py       #    REST API
│   │   │   ├── auth/routes.py      #    登录认证
│   │   │   └── ingest/cli.py       #    CLI 命令
│   │   ├── models/                 #    数据模型（7 张表）
│   │   ├── services/               #    业务逻辑层
│   │   ├── templates/              #    Jinja2 模板
│   │   └── static/                 #    静态资源
│   ├── migrations/                 #    Alembic 数据库迁移
│   ├── requirements.txt
│   └── README.md
│
├── mobile-backend/                 # ④ 移动端后端 API
│   ├── app.py                      #    Flask 主应用
│   ├── Dockerfile
│   ├── docker-compose.yml
│   ├── .env.example                #    环境变量模板
│   ├── requirements.txt
│   └── README.md
│
└── android/                        # ⑤ Android 客户端
    ├── app/src/main/java/.../
    │   ├── Alert.kt                #    告警数据模型
    │   ├── ApiService.kt           #    API 调用封装
    │   ├── LoginActivity.kt        #    登录页
    │   ├── MainActivity.kt         #    主页 + NFC
    │   ├── AlertFragment.kt        #    告警列表
    │   ├── AlertDetailActivity.kt  #    告警详情
    │   └── ...
    ├── build.gradle.kts
    └── README.md
```

---

## ✨ 功能特性

| 层级 | 模块 | 功能 |
|------|------|------|
| 🔵 感知层 | `csi_send` | 100Hz 固定 MCS0 UDP 发包，为 CSI 采集提供稳定信号源 |
| 🔵 感知层 | `csi_recv` | 实时 CSI 采集 → AGC 归一化 → 子载波方差 → 滑窗阈值判定 → 跌倒确认 |
| 🔵 感知层 | `csi_recv` | WS2812B RGB LED 状态指示（绿/橙/红 三种颜色 + 闪烁模式） |
| 🟢 云端层 | `esp-admin` | 设备管理、区域管理、NFC 标签管理、用户权限、UDP 数据接收 |
| 🟢 云端层 | `mobile-backend` | 用户注册/登录（JWT）、NFC 区域绑定、告警查询与状态更新 |
| 🟡 用户层 | `android` | 告警实时轮询（3s）、状态标记、NFC 刷卡绑定、推送通知 |

### LED 状态说明

| 状态 | LED 表现 | 含义 |
|------|----------|------|
| 🟢 绿灯常亮 | — | 静止监测中 |
| 🟠 橙灯慢闪 (1Hz) | — | 检测到运动 |
| 🔴 红灯常亮 | — | 疑似跌倒（等待确认） |
| 🔴 红灯快闪 (4Hz) | — | 跌倒确认 → 自动上报云端 |

> 确认延迟：跌倒后约 **5.5 秒**（2.5s 前置静默 + 3s 二次确认）

---

## 🔩 硬件清单

| 组件 | 数量 | 说明 |
|------|------|------|
| ESP32-S3 开发板 | ×2 | 一块发送，一块接收 |
| WS2812B RGB LED | ×1 | 状态指示（接接收板 GPIO48，串 470Ω 电阻） |
| 手机热点 / 路由器 | ×1 | 为 ESP32 提供网络连接 |
| 服务器 / PC | ×1 | 运行 esp-admin + mobile-backend |
| NFC 标签（可选） | ×N | 用于 Android 端区域绑定 |
| Android 手机（可选） | ×1 | 运行告警客户端（需支持 NFC） |

### 接线图

```
ESP32-S3 (接收板) GPIO48 ──[470Ω]──→ WS2812B DI
ESP32-S3 (接收板) 5V     ───────────→ WS2812B VDD
ESP32-S3 (接收板) GND    ───────────→ WS2812B GND
```

---

## 🚀 快速开始

### 前置要求

- [ESP-IDF v5.3.4](https://docs.espressif.com/projects/esp-idf/en/v5.3.4/)（接收板）/ v5.5.0+（发送板）
- Python 3.10+
- MySQL 8.0（或 SQLite 用于开发）
- Android Studio（用于构建 Android 客户端）

### 1. 刷写 ESP32 固件

**发送板：**

```bash
cd csi_send
idf.py set-target esp32s3
idf.py build
idf.py flash -p /dev/ttyUSB0 monitor
```

**接收板：**

```bash
cd csi_recv
# 先编辑 main/app_main.c 中的 WiFi 和服务器配置
idf.py set-target esp32s3
idf.py build
idf.py flash -p /dev/ttyUSB1 monitor
```

### 2. 部署云端服务

```bash
# 管理后台 + UDP 接收
cd esp-admin
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 配置环境变量
export SECRET_KEY="your-secret-key"
export DATABASE_URL="mysql://user:pass@localhost/esp_admin"
export APP_API_KEY="your-api-key"

# 初始化数据库
flask db upgrade
flask ingest init-admin

# 启动（两个终端）
flask run --host=0.0.0.0 --port=5000 &   # Web 管理后台
flask ingest udp                          # UDP 数据接收
```

```bash
# 移动端 API
cd mobile-backend
cp .env.example .env   # 编辑填入数据库信息
docker compose up -d   # 或直接 python app.py
```

### 3. 构建 Android 客户端

用 Android Studio 打开 `android/` 目录，修改 `ApiService.kt` 中的 `BASE_URL` 为你的服务器地址，然后 Build → Run。

---

## 📦 子模块说明

### csi_send — CSI 发送板固件

- **功能：** 纯 UDP 发包机，连接接收板的 AP（SSID: `csi_recv`），以 100Hz 频率发送固定大小数据包
- **关键优化：** 固定 MCS0 发送速率，避免速率自适应导致的 CSI 振幅跳变
- **目标芯片：** ESP32-S3 / ESP32-C3 / ESP32-C5 / ESP32-C6

### csi_recv — CSI 接收板固件（核心）

- **功能：** APSTA 双模 — 自建 AP 供发送板连接 + STA 连外网上报云端
- **核心算法：** CSI → 子载波振幅 → AGC 归一化 → 子载波方差 → 滑窗 + 三条件阈值判定
- **外设：** WS2812B RGB LED（GPIO48），RMT 驱动
- **模式开关：** `CSI_RAW_DUMP_MODE`（串口采集）/ `FALL_DETECT_ENABLE`（推理 + LED + 上报）
- **详细说明：** 参见 [`csi_recv/README.md`](csi_recv/README.md)

### esp-admin — Web 管理后台

- **功能：** 设备全生命周期管理、区域管理、NFC 标签管理、用户权限、CSI 事件查看
- **技术栈：** Flask + SQLAlchemy + Flask-Migrate + Jinja2 + Gunicorn
- **CLI 命令：** `flask ingest udp`（UDP 接收）、`flask ingest init-admin`（初始化管理员）、`flask ingest cleanup`（数据清理）
- **详细说明：** 参见 [`esp-admin/README.md`](esp-admin/README.md)

### mobile-backend — 移动端 API 服务

- **功能：** 为 Android 客户端提供 REST API：注册/登录（JWT）、NFC 绑定、告警查询、状态更新
- **技术栈：** Flask + PyMySQL + bcrypt + PyJWT + Gunicorn + Docker
- **详细说明：** 参见 [`mobile-backend/README.md`](mobile-backend/README.md)

### android — Android 客户端

- **功能：** 告警实时轮询（3s）、状态标记（未处理/误报/已处理）、NFC 区域绑定、推送通知、桌面角标
- **最低 SDK：** Android 7.0 (API 24)
- **技术栈：** Kotlin + OkHttp + Material Design 3 + AndroidX Security Crypto
- **详细说明：** 参见 [`android/README.md`](android/README.md)

---

## 🔬 算法原理

### 1. 单帧特征提取

```
128 字节 CSI → 64 子载波 (I, Q) → 振幅 A = √(I²+Q²)
    → AGC 归一化: A' = A / mean(A)
    → 子载波间方差: var = Σ(A'_i - 1.0)² / 64
```

**物理意义：** 子载波方差反映频率选择性衰落程度。人体静止时多径稳定 → 方差极小；动作时不同子载波受到不同程度遮挡/反射 → 方差增大。

### 2. 滑动窗口 + 三条件阈值判定

```
条件 1: 尖峰前连续静默 ≥ 29 窗 (≈2.5s)
  AND
条件 2: 尖峰密度 ≤ 8 窗（排除持续运动）
  AND
条件 3: 尖峰后连续静默 ≥ 29 窗 (≈2.5s)
  ↓
疑似跌倒 → 3s 内若有运动则取消 → 3s 内持续静默则确认
```

### 3. PC 端 CNN 对比方案

AGC 方差曲线 → 1D-CNN，3-fold CV 准确率 **96%**（详见 `csi_recv/tools/train_cnn.py`）。由于模型体积和推理延迟原因，未部署到 ESP32 边缘端。

---

## ⚠️ ESP32-S3 CSI 硬件局限

| 局限 | 说明 | 影响 |
|------|------|------|
| **AGC（自动增益控制）** | μs 级实时调节接收增益 | 摔倒冲击的振幅尖峰被"压扁"，与走路波动区分度降低 |
| **int8 量化精度** | I/Q 采样仅 8-bit，动态范围 256 级 | 走路和摔倒的信号都已触及量化天花板 |
| **晶振相位噪声** | ±25ppm 低成本晶振，2.4GHz 载波漂移 ±60kHz | 相位/多普勒信息不可用，只能依赖幅度特征 |

> 以上局限使得本系统只能依赖**子载波间相对幅度形状**（频率选择性衰落）作为特征。阈值需在**实际部署环境**中重新标定，不同房间的多径结构差异显著。

---

## 📄 许可证

本项目基于 [MIT License](LICENSE) 开源。

---

## 🙏 致谢

- [Espressif ESP-IDF](https://github.com/espressif/esp-idf) — ESP32 官方开发框架
- [Espressif ESP-CSI](https://github.com/espressif/esp-csi) — ESP32 CSI 示例与工具

---

*Made with ❤️ by Liu Yuan*
