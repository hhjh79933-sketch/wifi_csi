package com.example.android

import android.content.Intent
import android.os.Bundle
import android.widget.Button
import android.widget.EditText
import android.widget.TextView
import android.widget.Toast
import androidx.activity.enableEdgeToEdge
import androidx.appcompat.app.AppCompatActivity
import okhttp3.*
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject
import java.io.IOException

class RegisterActivity : AppCompatActivity() {

    private lateinit var etUsername: EditText
    private lateinit var etPassword: EditText
    private lateinit var btnRegister: Button
    private lateinit var tvToLogin: TextView

    private val client = OkHttpClient.Builder()
        .connectTimeout(10, java.util.concurrent.TimeUnit.SECONDS)
        .readTimeout(10, java.util.concurrent.TimeUnit.SECONDS)
        .writeTimeout(10, java.util.concurrent.TimeUnit.SECONDS)
        .build()

    override fun onCreate(savedInstanceState: Bundle?) {

        super.onCreate(savedInstanceState)

        enableEdgeToEdge()

        setContentView(R.layout.activity_register)

        // 返回
        findViewById<android.widget.TextView>(R.id.tvBack).setOnClickListener {
            finish()
        }

        etUsername = findViewById(R.id.etUsername)
        etPassword = findViewById(R.id.etPassword)

        btnRegister = findViewById(R.id.btnRegister)

        tvToLogin = findViewById(R.id.tvToLogin)

        btnRegister.setOnClickListener {
            register()
        }

        tvToLogin.setOnClickListener {
            startActivity(Intent(this, LoginActivity::class.java))
            finish()
        }
    }

    private fun register() {

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
        if (password.length < 4) {
            etPassword.error = "密码不能少于4位"
            return
        }

        val json = JSONObject()

        json.put("username", username)
        json.put("password", password)

        val mediaType = "application/json".toMediaType()

        val body = json.toString().toRequestBody(mediaType)

        val request = Request.Builder()
            .url("${ApiService.BASE_URL}/register")
            .post(body)
            .build()

        btnRegister.isEnabled = false
        btnRegister.text = "注册中..."

        client.newCall(request).enqueue(object : Callback {

            override fun onFailure(call: Call, e: IOException) {

                runOnUiThread {
                    btnRegister.isEnabled = true
                    btnRegister.text = "注  册"

                    Toast.makeText(
                        this@RegisterActivity,
                        "服务器连接失败",
                        Toast.LENGTH_SHORT
                    ).show()
                }
            }

            override fun onResponse(call: Call, response: Response) {

                val result = response.body?.string() ?: ""

                val obj = JSONObject(result)

                runOnUiThread {

                    Toast.makeText(
                        this@RegisterActivity,
                        obj.getString("message"),
                        Toast.LENGTH_SHORT
                    ).show()

                    if (obj.getString("status") == "success") {
                        startActivity(Intent(this@RegisterActivity, LoginActivity::class.java))
                        finish()
                    } else {
                        btnRegister.isEnabled = true
                        btnRegister.text = "注  册"
                    }
                }
            }
        })
    }
}