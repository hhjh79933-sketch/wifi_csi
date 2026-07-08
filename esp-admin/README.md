# ESP32 Admin

ESP32 感知项目的 Web 管理端 —— 设备管理、区域绑定、NFC 标签管理、事件查看与 UDP 数据接收的后台系统。

## 功能概览

- **Dashboard** — 设备状态总览（正常 / 异常 / 停用）、设备/事件数量、最近心跳与 CSI 事件时间
- **设备管理** — 设备注册（MAC 地址）、查看详情、绑定/解绑区域、心跳状态监控
- **区域管理** — 区域的增删改、启停用切换、查看区域下的 NFC 标签与用户分配记录
- **NFC 标签管理** — NFC 标签 UID 注册、绑定到区域（供手机 App 调用 API 完成设备-区域绑定）
- **用户管理** — 创建用户、分配管理区域、操作日志记录
- **事件查看** — 查看 CSI 感知事件（`csi_evt`）的详细数据，支持特征、样本等原始 JSON 美化展示
- **REST API** — 提供 `/api/*` 接口供移动端 App 调用（API Key 认证）
- **UDP 数据接收** — 内置 CLI 命令 `flask ingest udp`，监听 UDP 端口接收 ESP32 上报的 JSON 数据并持久化

## 技术栈

| 类别       | 技术                                |
| ---------- | ----------------------------------- |
| 后端框架   | Flask 3.x                           |
| ORM / DB   | SQLAlchemy + Flask-Migrate          |
| 数据库     | SQLite（默认）/ MySQL（PyMySQL）    |
| 模板引擎   | Jinja2（服务端渲染）                |
| CSRF 防护  | Flask-WTF                           |
| WSGI 服务  | Gunicorn                            |

## 项目结构

```
esp-admin/
├── wsgi.py                  # WSGI 入口
├── requirements.txt         # Python 依赖
├── app/
│   ├── __init__.py          # 应用工厂 create_app()
│   ├── config.py            # 配置加载（环境变量驱动）
│   ├── extensions.py        # Flask 扩展实例（db, migrate, csrf）
│   ├── blueprints/
│   │   ├── admin/routes.py  # 管理后台页面路由
│   │   ├── api/routes.py    # REST API 路由（App 端调用）
│   │   ├── auth/routes.py   # 登录/登出路由
│   │   └── ingest/cli.py    # CLI 命令（UDP 监听、admin 初始化、清理）
│   ├── models/
│   │   ├── device.py             # 设备模型
│   │   ├── area.py               # 区域模型
│   │   ├── device_area_binding.py # 设备-区域绑定（带时间窗口）
│   │   ├── event.py              # 事件模型（hb / csi_evt）
│   │   ├── nfc_tag.py            # NFC 标签模型
│   │   ├── user.py               # 用户模型
│   │   └── user_area_assignment.py # 用户-区域分配日志
│   ├── services/
│   │   ├── auth.py      # 认证服务（登录、session、权限装饰器）
│   │   ├── binding.py   # 设备-区域绑定逻辑、NFC 标签查询
│   │   └── ingest.py    # UDP 数据解析与持久化
│   ├── templates/       # Jinja2 模板（admin/, auth/, errors/）
│   └── static/
│       └── style.css    # 样式（纯 CSS，无框架依赖）
├── migrations/          # Alembic 数据库迁移
└── instance/            # 运行时数据（SQLite 默认存放位置）
```

## 快速开始

### 1. 环境准备

- Python 3.10+
- 推荐使用虚拟环境

```bash
cd esp-admin
python -m venv .venv

# Linux / macOS
source .venv/bin/activate

# Windows
.venv\Scripts\activate

pip install -r requirements.txt
```

### 2. 配置环境变量

```bash
# 必填
export SECRET_KEY="your-secret-key-here"

# 可选（不设置则默认使用 SQLite）
export DATABASE_URL="sqlite:///instance/esp_admin.sqlite"
# 或 MySQL：
# export DATABASE_URL="mysql://user:password@localhost:3306/esp_admin"

# 管理员账号（用于 flask ingest init-admin 创建初始管理员）
export ADMIN_USERNAME="admin"
export ADMIN_PASSWORD="your-admin-password"

# App API Key（手机 App 调用 /api/bind 时使用）
export APP_API_KEY="your-app-api-key"

# 可选配置（有默认值）
export HEARTBEAT_TIMEOUT_SECONDS="180"   # 心跳超时阈值（秒）
export DEVICE_AUTO_REGISTER="true"       # 是否自动注册未知 MAC 设备
export UDP_BIND="0.0.0.0"               # UDP 监听地址
export UDP_PORT="9000"                   # UDP 监听端口
```

### 3. 初始化数据库

```bash
flask db upgrade
flask ingest init-admin
```

### 4. 启动应用

**开发模式：**

```bash
flask run --host=0.0.0.0 --port=5000
```

**生产模式（Gunicorn）：**

```bash
gunicorn -w 4 -b 0.0.0.0:8000 wsgi:app
```

### 5. 启动 UDP 数据接收

```bash
flask ingest udp
```

## CLI 命令

| 命令                     | 说明                                       |
| ------------------------ | ------------------------------------------ |
| `flask ingest udp`       | 启动 UDP 监听，接收 ESP32 上报的 JSON 数据 |
| `flask ingest init-admin` | 根据环境变量创建初始管理员账号（幂等）     |
| `flask ingest cleanup`   | 清理 N 天前的非心跳事件（默认 14 天）      |
| `flask db upgrade`       | 执行数据库迁移                             |
| `flask db migrate -m ""` | 生成新的数据库迁移脚本                     |

### cleanup 选项

```bash
flask ingest cleanup --days 30          # 清理 30 天前的数据
flask ingest cleanup --dry-run          # 仅显示将要删除的数量，不实际删除
```

## REST API

API 接口前缀为 `/api`，CSRF 保护已对该蓝图豁免。

### GET /api/devices

获取所有设备列表，包含心跳状态。

**响应示例：**

```json
{
  "devices": [
    {
      "id": 1,
      "mac": "aa:bb:cc:dd:ee:ff",
      "alias": null,
      "last_seen_at": "2026-07-08T12:00:00+00:00",
      "last_hb_at": "2026-07-08T12:00:00+00:00",
      "heartbeat_status": "正常",
      "status": "正常"
    }
  ]
}
```

### GET /api/events

获取最近的 CSI 事件列表（不含心跳事件），最多返回 200 条。

### POST /api/bind

App 端通过 NFC 刷卡完成设备-区域绑定。

**请求头：**
```
X-API-Key: <APP_API_KEY>
Content-Type: application/json
```

**请求体：**
```json
{
  "mac": "aa:bb:cc:dd:ee:ff",
  "nfc_uid": "04A1B2C3D4E5F6",
  "actor": "optional-username"
}
```

**响应示例：**
```json
{
  "ok": true,
  "changed": true,
  "device": { "id": 1, "mac": "aa:bb:cc:dd:ee:ff", "..." : "..." },
  "area": { "id": 1, "name": "客厅", "..." : "..." },
  "tag": { "id": 1, "uid": "04A1B2C3D4E5F6", "..." : "..." },
  "binding": { "id": 1, "device_id": 1, "area_id": 1, "..." : "..." }
}
```

## 数据模型概览

### 设备 (Device)
- `mac` — MAC 地址（唯一标识）
- `last_seen_at` — 最后一次收到任何数据的时间
- `last_hb_at` — 最后一次收到心跳的时间
- `heartbeat_status` — 根据超时阈值计算：`正常` / `异常`

### 区域 (Area)
- `name` — 区域名称（唯一）
- `is_active` — 启用/停用状态

### 设备-区域绑定 (DeviceAreaBinding)
- 带时间窗口的绑定记录（`effective_from` / `effective_to`）
- 支持 `app` 和 `web` 两种绑定来源
- 记录操作人和 NFC UID

### 事件 (Event)
- `type` — `hb`（心跳）或 `csi_evt`（CSI 感知事件）
- CSI 事件包含：`seq`（序号）、`state`（状态）、`feat`（特征）、`delta`（变化）、`samples`（采样数据）等
- `raw_or_json` — 原始上报数据（便于排查）

### NFC 标签 (NfcTag)
- `uid` — NFC 标签唯一 ID
- 绑定到一个 `Area`

### 用户 (User)
- `is_admin` — 管理员标识
- `current_area_id` — 当前分配的管理区域
- `UserAreaAssignment` — 区域分配操作日志

## 设备状态说明

| 状态 | 含义                                 |
| ---- | ------------------------------------ |
| 正常 | 有心跳且在超时阈值内                 |
| 异常 | 有心跳但已超过超时阈值               |
| 停用 | 设备未绑定到任何区域，或绑定区域已停用 |

## 数据库支持

- **SQLite**（默认）— 开箱即用，适合开发和小规模部署
- **MySQL** — 通过 `DATABASE_URL` 环境变量配置，自动使用 PyMySQL 驱动

如果提供的 `DATABASE_URL` 以 `mysql://` 开头，系统会自动转换为 `mysql+pymysql://`。

## License

MIT
