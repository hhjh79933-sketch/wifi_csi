# ESP32 跌倒感知系统 - 移动端后端

基于 Flask 的移动端后端服务，为 ESP32 WiFi 跌倒感知系统提供用户管理、NFC 区域绑定和告警推送等 API 支持。

## 功能特性

- 🔐 **用户认证**：注册 / 登录，基于 bcrypt 密码哈希 + JWT Token
- 📍 **NFC 区域绑定**：用户通过 NFC 标签绑定到指定区域，支持绑定 / 解绑
- 🚨 **跌倒告警查询**：根据用户当前绑定区域，拉取关联设备的 CSI 跌倒事件
- 📝 **事件备注**：支持对告警事件添加备注（不少于 15 字）
- ✅ **告警状态更新**：标记告警事件处理状态
- 🐳 **Docker 部署**：基于 Gunicorn 的生产级部署，开箱即用

## 技术栈

| 组件 | 技术 |
|------|------|
| Web 框架 | Flask 2.0 |
| 数据库 | MySQL (PyMySQL) |
| 密码加密 | bcrypt |
| 认证 | PyJWT (HS256) |
| WSGI 服务器 | Gunicorn |
| 容器化 | Docker + Docker Compose |

## 项目结构

```
mobile-backend/
├── app.py              # Flask 主应用（所有 API 路由）
├── requirements.txt    # Python 依赖
├── Dockerfile          # Docker 镜像构建文件
├── docker-compose.yml  # Docker Compose 编排
├── .dockerignore       # Docker 构建忽略文件
├── .gitignore          # Git 忽略文件
└── .env.example        # 环境变量示例文件
```

## API 接口

### 基础

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/` | 健康检查 |

### 用户模块

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/register` | 用户注册 |
| POST | `/login` | 用户登录，返回 JWT Token |
| POST | `/verify_password` | 验证原密码 |
| POST | `/change_password` | 修改密码 |

### 区域绑定

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/bind_nfc` | NFC 绑定到区域 |
| POST | `/unbind_nfc` | 解绑当前区域 |
| GET | `/get_current_area` | 查询用户当前绑定区域 |

### 告警

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/get_alerts` | 获取用户区域的跌倒告警 |
| POST | `/update_alert_state` | 更新告警状态 |
| POST | `/update_note` | 添加 / 修改事件备注 |

## 快速开始

### 1. 克隆项目

```bash
git clone https://github.com/your-username/mobile-backend.git
cd mobile-backend
```

### 2. 配置环境变量

```bash
cp .env.example .env
```

编辑 `.env` 文件，填入实际的数据库连接信息和 JWT 密钥：

```ini
DB_HOST=your_db_host
DB_USER=your_db_user
DB_PASSWORD=your_db_password
DB_NAME=esp_admin
SECRET_KEY=your_random_secret_key
```

### 3. 使用 Docker Compose 启动（推荐）

```bash
docker compose up -d
```

### 4. 本地开发运行

```bash
# 创建虚拟环境
python -m venv venv
source venv/bin/activate  # Linux/Mac
# venv\Scripts\activate   # Windows

# 安装依赖
pip install -r requirements.txt

# 配置环境变量（Linux/Mac）
export $(cat .env | xargs)

# 配置环境变量（Windows PowerShell）
Get-Content .env | ForEach-Object { if ($_ -match '^([^#].+?)=(.+)$') { [System.Environment]::SetEnvironmentVariable($matches[1], $matches[2]) } }

# 启动服务
python app.py
```

服务默认运行在 `http://localhost:5000`。

## 数据库表结构

项目依赖以下 MySQL 数据表（需提前创建）：

| 表名 | 说明 |
|------|------|
| `users` | 用户表（id, username, password_hash, is_admin, current_area_id, created_at） |
| `areas` | 区域表（id, name） |
| `nfc_tags` | NFC 标签表（uid, area_id, is_active） |
| `devices` | ESP32 设备表 |
| `device_area_bindings` | 设备-区域绑定关系（device_id, area_id, effective_from, effective_to） |
| `events` | 事件表（id, device_id, type, state, note, created_at） |
| `user_area_assignments` | 用户-区域绑定历史记录 |

## 安全说明

- 所有敏感配置（数据库连接、JWT 密钥）通过环境变量注入，**不要**硬编码在代码中
- `.env` 文件已加入 `.gitignore`，不会被提交到仓库
- 密码使用 bcrypt 加盐哈希存储，不保存明文
- 生产环境请务必使用强随机字符串替换 `SECRET_KEY`

## License

MIT
