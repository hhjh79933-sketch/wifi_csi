package com.example.android

import android.content.Intent
import android.os.Bundle
import android.view.View
import android.widget.Button
import android.widget.EditText
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import androidx.fragment.app.Fragment
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey

class ProfileFragment : Fragment(R.layout.fragment_profile) {

    private lateinit var tvUsername: TextView
    private lateinit var etOldPassword: EditText
    private lateinit var etNewPassword: EditText
    private lateinit var etConfirmPassword: EditText

    private lateinit var btnVerify: Button
    private lateinit var btnSave: Button
    private lateinit var tvGroupId: TextView
    private lateinit var btnScan: Button
    private lateinit var btnUnbind: Button
    private lateinit var btnLogout: Button

    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {

        super.onViewCreated(view, savedInstanceState)

        tvUsername = view.findViewById(R.id.tvUsername)
        etOldPassword = view.findViewById(R.id.etOldPassword)
        etNewPassword = view.findViewById(R.id.etNewPassword)
        etConfirmPassword = view.findViewById(R.id.etConfirmPassword)
        btnVerify = view.findViewById(R.id.btnVerify)
        btnSave = view.findViewById(R.id.btnSave)
        tvGroupId = view.findViewById(R.id.tvGroupId)
        btnScan = view.findViewById(R.id.btnScanNFC)
        btnUnbind = view.findViewById(R.id.btnUnbind)
        btnLogout = view.findViewById(R.id.btnLogout)

        // 禁用状态下点击提示
        val disableHint = { v: View ->
            v.setOnClickListener {
                if (!v.isFocusable) Toast.makeText(requireContext(), "请先输入旧密码", Toast.LENGTH_SHORT).show()
            }
        }
        disableHint(etNewPassword)
        disableHint(etConfirmPassword)

        // 初始锁住新密码区域
        lockNewPasswordFields()

        // =========================
        // 读取用户名
        // =========================

        val masterKey = MasterKey.Builder(requireContext())
            .setKeyScheme(MasterKey.KeyScheme.AES256_GCM)
            .build()

        val userSp = EncryptedSharedPreferences.create(
            requireContext(),
            "user_secure",
            masterKey,
            EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
            EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM
        )

        val username =
            userSp.getString("username", "未知用户")

        tvUsername.text = username

        // =========================
        // NFC绑定
        // =========================

        btnScan.setOnClickListener {

            val mainActivity = activity as? MainActivity

            if (mainActivity == null) {

                Toast.makeText(
                    requireContext(),
                    "页面错误",
                    Toast.LENGTH_SHORT
                ).show()

                return@setOnClickListener
            }

            mainActivity.enableNFCScan()

            Toast.makeText(
                requireContext(),
                "请将NFC标签贴近手机",
                Toast.LENGTH_LONG
            ).show()
        }

        btnUnbind.setOnClickListener {
            AlertDialog.Builder(requireContext())
                .setTitle("解除绑定")
                .setMessage("确定要解除当前检测区域的绑定吗？\n解除后将无法收到该区域的异常通知。")
                .setPositiveButton("确定解除") { _, _ ->
                    val username = tvUsername.text.toString()
                    ApiService().unbindNFC(username) { success, message ->
                        requireActivity().runOnUiThread {
                            Toast.makeText(requireContext(), message, Toast.LENGTH_SHORT).show()
                            if (success) {
                                tvGroupId.text = "当前检测区域：未绑定"
                            }
                        }
                    }
                }
                .setNegativeButton("取消", null)
                .show()
        }

        // 退出登录
        btnLogout.setOnClickListener {
            AlertDialog.Builder(requireContext())
                .setTitle("退出登录")
                .setMessage("确定要退出当前账号吗？")
                .setPositiveButton("确定退出") { _, _ ->
                    userSp.edit()
                        .remove("username")
                        .remove("token")
                        .putBoolean("auto_login", false)
                        .apply()
                    val intent = Intent(requireContext(), MainEntryActivity::class.java)
                        intent.flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK
                        startActivity(intent)
                    requireActivity().finish()
                }
                .setNegativeButton("取消", null)
                .show()
        }

        btnVerify.setOnClickListener {

            val oldPassword =
                etOldPassword.text.toString()

            if (oldPassword.isEmpty()) {

                Toast.makeText(
                    requireContext(),
                    "请输入原密码",
                    Toast.LENGTH_SHORT
                ).show()

                return@setOnClickListener
            }

            // 后续连接服务器验证

            val username = tvUsername.text.toString()

            ApiService().verifyPassword(
                username,
                oldPassword
            ) { success, message ->

                requireActivity().runOnUiThread {

                    Toast.makeText(
                        requireContext(),
                        message,
                        Toast.LENGTH_SHORT
                    ).show()

                    if (success) {

                        unlockNewPasswordFields()
                    }
                }
            }
        }
        // =========================
        // 保存密码
        // =========================

        btnSave.setOnClickListener {

            if (!btnSave.isEnabled) {
                Toast.makeText(requireContext(), "请先输入旧密码", Toast.LENGTH_SHORT).show()
                return@setOnClickListener
            }

            val newPassword = etNewPassword.text.toString().trim()
            val confirmPassword = etConfirmPassword.text.toString().trim()

            if (newPassword.isEmpty()) {

                Toast.makeText(
                    requireContext(),
                    "请输入新密码",
                    Toast.LENGTH_SHORT
                ).show()

                return@setOnClickListener
            }

            if (newPassword.length < 4) {
                Toast.makeText(
                    requireContext(),
                    "新密码不能少于4位",
                    Toast.LENGTH_SHORT
                ).show()
                return@setOnClickListener
            }

            val oldPassword = etOldPassword.text.toString().trim()
            if (newPassword == oldPassword) {
                Toast.makeText(
                    requireContext(),
                    "新密码不能与原密码相同",
                    Toast.LENGTH_SHORT
                ).show()
                return@setOnClickListener
            }

            if (newPassword != confirmPassword) {

                Toast.makeText(
                    requireContext(),
                    "两次密码输入不一致",
                    Toast.LENGTH_SHORT
                ).show()

                return@setOnClickListener
            }

            val username = tvUsername.text.toString()

            ApiService().changePassword(
                username,
                newPassword
            ) { success, message ->

                requireActivity().runOnUiThread {

                    Toast.makeText(
                        requireContext(),
                        message,
                        Toast.LENGTH_SHORT
                    ).show()

                    if (success) {

                        lockNewPasswordFields()
                    }
                }
            }
        }

        refreshBindingInfo()
    }

    private fun lockNewPasswordFields() {
        etOldPassword.text?.clear()
        etNewPassword.text?.clear()
        etConfirmPassword.text?.clear()
        etNewPassword.isFocusable = false
        etNewPassword.isFocusableInTouchMode = false
        etNewPassword.alpha = 0.5f
        etConfirmPassword.isFocusable = false
        etConfirmPassword.isFocusableInTouchMode = false
        etConfirmPassword.alpha = 0.5f
        btnSave.isEnabled = false
        btnSave.alpha = 0.5f
    }

    private fun unlockNewPasswordFields() {
        etNewPassword.isFocusable = true
        etNewPassword.isFocusableInTouchMode = true
        etNewPassword.alpha = 1f
        etConfirmPassword.isFocusable = true
        etConfirmPassword.isFocusableInTouchMode = true
        etConfirmPassword.alpha = 1f
        btnSave.isEnabled = true
        btnSave.alpha = 1f
    }

    override fun onResume() {
        super.onResume()
        lockNewPasswordFields()
        refreshBindingInfo()
    }

    override fun onHiddenChanged(hidden: Boolean) {
        super.onHiddenChanged(hidden)
        if (hidden) {
            // 用户切换到其他页面时，清空所有密码输入框并重置状态
            lockNewPasswordFields()
        }
    }

    fun refreshBindingInfo() {

        if (!isAdded) return

        val masterKey = MasterKey.Builder(requireContext())
            .setKeyScheme(MasterKey.KeyScheme.AES256_GCM)
            .build()

        val userSp = EncryptedSharedPreferences.create(
            requireContext(),
            "user_secure",
            masterKey,
            EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
            EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM
        )

        val username =
            userSp.getString(
                "username",
                ""
            ) ?: ""

        ApiService().getCurrentArea(
            username
        ) { areaName ->

            requireActivity().runOnUiThread {

                android.util.Log.e(
                    "AREA_DEBUG",
                    "服务器返回=$areaName"
                )
                if (areaName == null) {

                    tvGroupId.text =
                        "当前监测区域：未绑定"

                } else {

                    tvGroupId.text =
                        "当前监测区域：$areaName"
                }
            }
        }
    }
}