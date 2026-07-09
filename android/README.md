# 防护检测 - Android 客户端

基于 ESP32 物联网感知系统的 Android 客户端应用，用于接收和查看病房/区域异常告警信息，支持 NFC 绑定检测区域。

## 功能概览

- **用户系统**：注册、登录、自动登录、密码修改
- **异常告警**：实时轮询拉取告警列表，3 秒自动刷新
- **告警状态管理**：支持标记为「未处理」「误报」「已处理」
- **告警详情**：查看告警详情，添加处理备注（不少于 15 字）
- **日期筛选**：按日期筛选历史告警记录
- **NFC 绑定**：通过 NFC 标签绑定/解绑检测区域
- **推送通知**：新告警到达时发送系统通知
- **横幅提醒**：应用内顶部横幅通知新告警
- **角标计数**：底部导航栏 + 桌面图标显示未处理数量

## 技术栈

| 类别 | 技术 |
|------|------|
| 语言 | Kotlin |
| 最低 SDK | 24 (Android 7.0) |
| 目标 SDK | 36 |
| 网络请求 | OkHttp 4.12 |
| JSON 解析 | org.json |
| 安全存储 | AndroidX Security Crypto (EncryptedSharedPreferences) |
| UI 组件 | Material Design 3, RecyclerView, SwipeRefreshLayout |
| NFC | Android NFC API (前台调度) |
| 通知 | NotificationCompat + 桌面角标 |

## 项目结构

```
app/src/main/java/com/example/android/
├── Alert.kt                  # 告警数据模型
├── AlertAdapter.kt           # 告警列表 RecyclerView 适配器
├── AlertDetailActivity.kt    # 告警详情页
├── AlertFragment.kt          # 告警列表页（轮询、筛选、统计）
├── ApiService.kt             # 后端 API 调用封装
├── LoginActivity.kt          # 登录页
├── MainActivity.kt           # 主页面（NFC 扫描、横幅、角标、Fragment 管理）
├── MainEntryActivity.kt      # 入口页（自动登录检查）
├── NotificationHelper.kt     # 通知管理（推送 + 桌面角标）
├── ProfileFragment.kt        # 个人信息页（NFC 绑定、密码修改）
└── RegisterActivity.kt       # 注册页
```

## 快速开始

### 环境要求

- Android Studio Hedgehog (2023.1.1) 或更高版本
- JDK 11+
- Gradle 9.3+
- 一台支持 NFC 的 Android 设备（用于 NFC 绑定功能）

### 配置后端地址

1. 编辑 `app/src/main/java/com/example/android/ApiService.kt`，将 `BASE_URL` 修改为你的后端服务器地址：

```kotlin
companion object {
    const val BASE_URL = "http://your-server-ip:5000"
}
```

2. 编辑 `app/src/main/res/xml/network_security_config.xml`，将域名替换为你的服务器地址：

```xml
<domain-config cleartextTrafficPermitted="true">
    <domain includeSubdomains="true">your-server-ip</domain>
</domain-config>
```

> ⚠️ **生产环境建议**：部署到生产环境时，请使用 HTTPS 并移除 `cleartextTrafficPermitted` 配置。

### 构建与运行

```bash
# 使用 Gradle Wrapper 构建
./gradlew assembleDebug

# 或在 Android Studio 中直接 Run
```

## API 接口

应用依赖以下后端接口（需配合 ESP32 后端服务使用）：

| 接口 | 方法 | 说明 |
|------|------|------|
| `/register` | POST | 用户注册 |
| `/login` | POST | 用户登录，返回 token |
| `/get_alerts` | GET | 获取告警列表 |
| `/update_alert_state` | POST | 更新告警状态 |
| `/update_note` | POST | 更新告警备注 |
| `/bind_nfc` | POST | 绑定 NFC 标签与检测区域 |
| `/unbind_nfc` | POST | 解除 NFC 绑定 |
| `/get_current_area` | GET | 获取当前绑定的区域名称 |
| `/verify_password` | POST | 验证原密码 |
| `/change_password` | POST | 修改密码 |

## 许可证

请根据需要选择合适的开源许可证。

---

*此项目为 ESP32 物联网感知系统的 Android 客户端部分。*
