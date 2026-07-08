package com.example.android

import android.content.Intent
import android.content.SharedPreferences
import android.os.Bundle
import android.widget.Button
import android.widget.CheckBox
import android.widget.EditText
import android.widget.TextView
import android.widget.Toast
import androidx.activity.enableEdgeToEdge
import androidx.appcompat.app.AppCompatActivity
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey
import okhttp3.*
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject
import java.io.IOException

class LoginActivity : AppCompatActivity() {

    private lateinit var etUsername: EditText
    private lateinit var etPassword: EditText
    private lateinit var btnLogin: Button
    private lateinit var tvToRegister: TextView
    private lateinit var cbAutoLogin: CheckBox

    private val client = OkHttpClient.Builder()
        .connectTimeout(10, java.util.concurrent.TimeUnit.SECONDS)
        .readTimeout(10, java.util.concurrent.TimeUnit.SECONDS)
        .writeTimeout(10, java.util.concurrent.TimeUnit.SECONDS)
        .build()

    override fun onCreate(savedInstanceState: Bundle?) {

        super.onCreate(savedInstanceState)

        enableEdgeToEdge()

        setContentView(R.layout.activity_login)

        // 返回
        findViewById<android.widget.TextView>(R.id.tvBack).setOnClickListener {
            finish()
        }

        etUsername = findViewById(R.id.etUsername)
        etPassword = findViewById(R.id.etPassword)

        btnLogin = findViewById(R.id.btnLogin)

        tvToRegister = findViewById(R.id.tvToRegister)

        cbAutoLogin = findViewById(R.id.cbAutoLogin)

        btnLogin.setOnClickListener {
            login()
        }

        tvToRegister.setOnClickListener {

            startActivity(
                Intent(
                    this,
                    RegisterActivity::class.java
                )
            )
        }
    }

    private fun login() {

        val username = etUsername.text.toString().trim()
        val password = etPassword.text.toString().trim()

        if (username.isEmpty()) {
            etUsername.error = "请输入用户名"
            return
        }
        if (password.isEmpty()) {
            etPassword.error = "请输入密码"
            return
        }

        val json = JSONObject()

        json.put("username", username)
        json.put("password", password)

        val mediaType = "application/json".toMediaType()

        val body = json.toString().toRequestBody(mediaType)

        val request = Request.Builder()
            .url("${ApiService.BASE_URL}/login")
            .post(body)
            .build()

        btnLogin.isEnabled = false
        btnLogin.text = "登录中..."

        client.newCall(request).enqueue(object : Callback {

            override fun onFailure(call: Call, e: IOException) {

                runOnUiThread {
                    btnLogin.isEnabled = true
                    btnLogin.text = "登  录"

                    Toast.makeText(
                        this@LoginActivity,
                        "服务器连接失败",
                        Toast.LENGTH_SHORT
                    ).show()
                }
            }

            override fun onResponse(call: Call, response: Response) {

                val result = response.body?.string() ?: ""

                val obj = JSONObject(result)

                runOnUiThread {

                    if (obj.getString("status") == "success") {

                        val token = obj.getString("token")

                        val masterKey = MasterKey.Builder(this@LoginActivity)
                            .setKeyScheme(MasterKey.KeyScheme.AES256_GCM)
                            .build()

                        val sp = EncryptedSharedPreferences.create(
                            this@LoginActivity,
                            "user_secure",
                            masterKey,
                            EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
                            EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM
                        )

                        sp.edit()
                            .putString("username", username)
                            .putString("token", token)
                            .putBoolean("auto_login", cbAutoLogin.isChecked)
                            .apply()

                        Toast.makeText(
                            this@LoginActivity,
                            "登录成功",
                            Toast.LENGTH_SHORT
                        ).show()

                        startActivity(
                            Intent(
                                this@LoginActivity,
                                MainActivity::class.java
                            )
                        )

                        finish()

                    } else {

                        btnLogin.isEnabled = true
                        btnLogin.text = "登  录"

                        Toast.makeText(
                            this@LoginActivity,
                            obj.getString("message"),
                            Toast.LENGTH_SHORT
                        ).show()
                    }
                }
            }
        })
    }
}