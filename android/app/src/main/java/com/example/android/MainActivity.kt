package com.example.android

import android.animation.Animator
import android.animation.AnimatorListenerAdapter
import android.app.PendingIntent
import android.content.Intent
import android.content.IntentFilter
import android.nfc.NfcAdapter
import android.nfc.Tag
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.util.Log
import android.view.View
import android.view.ViewTreeObserver
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.fragment.app.Fragment
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey
import com.google.android.material.badge.BadgeDrawable
import com.google.android.material.bottomnavigation.BottomNavigationView

class MainActivity : AppCompatActivity() {

    private val handler = Handler(Looper.getMainLooper())

    private val api = ApiService()

    // NFC
    private var nfcAdapter: NfcAdapter? = null

    private lateinit var pendingIntent: PendingIntent

    private lateinit var intentFiltersArray: Array<IntentFilter>

    private var techListsArray: Array<Array<String>>? = null

    // 当前是否允许扫描
    var isScanning = false

    // ---------- 横幅通知 ----------
    private var bannerView: View? = null
    private var bannerTitle: TextView? = null
    private var bannerMessage: TextView? = null
    private var bannerClose: TextView? = null
    private var bannerAnimating = false
    private var bannerDismissRunnable: Runnable? = null

    // ---------- 角标 ----------
    private lateinit var badgeDrawable: BadgeDrawable
    private lateinit var notificationHelper: NotificationHelper

    // 开启扫描
    fun enableNFCScan() {

        isScanning = true

        Toast.makeText(
            this,
            "请将NFC标签贴近手机背面",
            Toast.LENGTH_SHORT
        ).show()
    }

    override fun onCreate(savedInstanceState: Bundle?) {

        super.onCreate(savedInstanceState)

        setContentView(R.layout.activity_main)

        // 初始化横幅
        bannerView = findViewById(R.id.bannerAlert)
        bannerTitle = findViewById(R.id.bannerTitle)
        bannerMessage = findViewById(R.id.bannerMessage)
        bannerClose = findViewById(R.id.bannerClose)

        bannerClose?.setOnClickListener {
            dismissBanner()
        }

        bannerView?.setOnClickListener {
            // 点击横幅 → 切换到告警页面
            dismissBanner()
            findViewById<BottomNavigationView>(R.id.bottomNav)
                .selectedItemId = R.id.nav_alert
        }

        initNFC()

        val bottomNav = findViewById<BottomNavigationView>(R.id.bottomNav)

        // 初始化角标
        notificationHelper = NotificationHelper(this)
        badgeDrawable = BadgeDrawable.create(this).apply {
            backgroundColor = 0xFFE53935.toInt()   // 红色背景
            badgeTextColor = 0xFFFFFFFF.toInt()     // 白色文字
            maxCharacterCount = 3                   // 最多显示 "99+"
            isVisible = false
        }
        bottomNav.getOrCreateBadge(R.id.nav_alert).apply {
            isVisible = false
            maxCharacterCount = 3
            backgroundColor = 0xFFE53935.toInt()
            badgeTextColor = 0xFFFFFFFF.toInt()
        }

        // 默认页面
        loadFragment(AlertFragment())

        bottomNav.setOnItemSelectedListener {

            when (it.itemId) {

                R.id.nav_alert -> {
                    loadFragment(AlertFragment())
                }

                R.id.nav_profile -> {
                    loadFragment(ProfileFragment())
                }
            }

            true
        }
    }

    // =========================
    // 初始化 NFC
    // =========================

    private fun initNFC() {

        nfcAdapter = NfcAdapter.getDefaultAdapter(this)

        if (nfcAdapter == null) {

            Toast.makeText(
                this,
                "当前设备不支持 NFC",
                Toast.LENGTH_LONG
            ).show()

            return
        }

        pendingIntent = PendingIntent.getActivity(
            this,
            0,
            Intent(
                this,
                MainActivity::class.java
            ).addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP),
            PendingIntent.FLAG_MUTABLE
        )

        // 不限制 NFC 类型
        techListsArray = null
    }

    // =========================
    // 开启 NFC 前台调度
    // =========================

    override fun onResume() {

        super.onResume()

        val tagDetected = IntentFilter(
            NfcAdapter.ACTION_TAG_DISCOVERED
        )

        intentFiltersArray = arrayOf(tagDetected)

        nfcAdapter?.enableForegroundDispatch(
            this,
            pendingIntent,
            intentFiltersArray,
            null
        )
    }

    // =========================
    // 关闭 NFC 前台调度
    // =========================

    override fun onPause() {

        super.onPause()

        nfcAdapter?.disableForegroundDispatch(this)
    }

    // =========================
    // NFC 扫描回调
    // =========================

    override fun onNewIntent(intent: Intent) {

        super.onNewIntent(intent)

        setIntent(intent)

        Log.d("NFC_DEBUG", "收到NFC")

        Log.d("NFC_DEBUG", "action = ${intent.action}")

        if (!isScanning) {

            Log.e("NFC_DEBUG", "当前未开启扫描")

            return
        }

        val tag: Tag? =
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {

                intent.getParcelableExtra(
                    NfcAdapter.EXTRA_TAG,
                    Tag::class.java
                )

            } else {

                @Suppress("DEPRECATION")
                intent.getParcelableExtra(NfcAdapter.EXTRA_TAG)
            }

        if (tag == null) {

            Log.e("NFC_DEBUG", "tag为空")

            Toast.makeText(
                this,
                "NFC读取失败",
                Toast.LENGTH_SHORT
            ).show()

            return
        }

        Log.e("NFC_DEBUG", "成功获取Tag")

        val tagId = tag.id

        if (tagId == null || tagId.isEmpty()) {

            Log.e("NFC_DEBUG", "UID为空")

            Toast.makeText(
                this,
                "无法读取UID",
                Toast.LENGTH_SHORT
            ).show()

            return
        }

        val uid = tagId.joinToString("") {

            "%02X".format(it)
        }

        Log.e("NFC_TEST", "UID = $uid")

        Toast.makeText(
            this,
            "读取成功: $uid",
            Toast.LENGTH_LONG
        ).show()

        isScanning = false

        uploadUID(uid)
    }

    // =========================
    // 上传 UID 到服务器
    // =========================

    private fun uploadUID(uid: String) {

        val masterKey = MasterKey.Builder(this)
            .setKeyScheme(MasterKey.KeyScheme.AES256_GCM)
            .build()

        val userSp = EncryptedSharedPreferences.create(
            this,
            "user_secure",
            masterKey,
            EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
            EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM
        )

        val username =
            userSp.getString("username", "") ?: ""

        api.bindNFC(username, uid) { success, message, areaName ->

            runOnUiThread {

                Toast.makeText(
                    this,
                    message,
                    Toast.LENGTH_LONG
                ).show()

                // 绑定成功
                if (success && areaName != null) {

                    // 刷新个人页面
                    val fragment =
                        supportFragmentManager.findFragmentById(R.id.frameLayout)

                    if (fragment is ProfileFragment) {

                        fragment.refreshBindingInfo()
                    }
                }
            }
        }
    }

    // =========================
    // 横幅通知
    // =========================

    /**
     * 显示应用内横幅通知（从顶部滑入）
     */
    fun showAlertBanner(room: String, message: String) {

        val banner = bannerView ?: return

        bannerTitle?.text = "⚠️ 病房 $room 异常"
        bannerMessage?.text = message

        // 取消之前的自动关闭任务
        bannerDismissRunnable?.let { handler.removeCallbacks(it) }

        if (banner.visibility == View.VISIBLE && !bannerAnimating) {
            // 已显示 → 直接更新文字，重置计时
            scheduleBannerDismiss()
            return
        }

        if (bannerAnimating) return

        bannerAnimating = true

        // 先测量实际高度
        banner.visibility = View.INVISIBLE

        banner.viewTreeObserver.addOnPreDrawListener(
            object : ViewTreeObserver.OnPreDrawListener {
                override fun onPreDraw(): Boolean {
                    banner.viewTreeObserver.removeOnPreDrawListener(this)

                    val bannerHeight = banner.height.coerceAtLeast(1)

                    // 初始位置：藏在屏幕上方
                    banner.translationY = -bannerHeight.toFloat()
                    banner.visibility = View.VISIBLE
                    banner.alpha = 0f

                    banner.animate()
                        .translationY(0f)
                        .alpha(1f)
                        .setDuration(300)
                        .setListener(object : AnimatorListenerAdapter() {
                            override fun onAnimationEnd(animation: Animator) {
                                bannerAnimating = false
                                scheduleBannerDismiss()
                            }
                        })
                        .start()

                    return true
                }
            }
        )
    }

    private fun scheduleBannerDismiss() {
        bannerDismissRunnable = Runnable {
            dismissBanner()
        }
        handler.postDelayed(bannerDismissRunnable!!, 4000)
    }

    private fun dismissBanner() {

        val banner = bannerView ?: return

        bannerDismissRunnable?.let { handler.removeCallbacks(it) }

        if (banner.visibility != View.VISIBLE || bannerAnimating) return

        bannerAnimating = true

        banner.animate()
            .translationY(-banner.height.toFloat())
            .alpha(0f)
            .setDuration(250)
            .setListener(object : AnimatorListenerAdapter() {
                override fun onAnimationEnd(animation: Animator) {
                    banner.visibility = View.GONE
                    bannerAnimating = false
                }
            })
            .start()
    }

    // =========================
    // 角标更新
    // =========================

    /**
     * 更新底部导航栏角标 + 桌面图标角标
     * @param count 未处理的异常数量
     */
    fun updateUnprocessedBadge(count: Int) {
        val badge = findViewById<BottomNavigationView>(R.id.bottomNav)
            .getOrCreateBadge(R.id.nav_alert)

        if (count <= 0) {
            badge.isVisible = false
            badge.clearNumber()
        } else {
            badge.isVisible = true
            badge.number = count
        }

        // 桌面图标角标
        notificationHelper.updateBadgeCount(count)
    }

    // =========================
    // Fragment切换
    // =========================

    private val TAG_ALERT = "fragment_alert"
    private val TAG_PROFILE = "fragment_profile"

    private fun loadFragment(fragment: Fragment) {

        val tag = if (fragment is AlertFragment) TAG_ALERT else TAG_PROFILE

        // 尝试复用已有 Fragment，避免重复创建
        val existing = supportFragmentManager.findFragmentByTag(tag)

        if (existing != null && existing.isVisible) {
            return  // 已经是当前页，不操作
        }

        val transaction = supportFragmentManager.beginTransaction()

        if (existing != null) {
            // 显示已有的 Fragment，隐藏另一个
            val otherTag = if (tag == TAG_ALERT) TAG_PROFILE else TAG_ALERT
            val other = supportFragmentManager.findFragmentByTag(otherTag)
            if (other != null) {
                transaction.hide(other)
            }
            transaction.show(existing)
        } else {
            // 首次创建，添加到容器
            val otherTag = if (tag == TAG_ALERT) TAG_PROFILE else TAG_ALERT
            val other = supportFragmentManager.findFragmentByTag(otherTag)
            if (other != null) {
                transaction.hide(other)
            }
            transaction.add(R.id.frameLayout, fragment, tag)
        }

        transaction.commitNowAllowingStateLoss()
    }
}