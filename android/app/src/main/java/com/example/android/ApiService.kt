package com.example.android

import okhttp3.*
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONArray
import org.json.JSONObject
import java.io.IOException
import android.util.Log

class ApiService {

    companion object {
        // 请将此处替换为你自己的后端服务器地址
        const val BASE_URL = "http://your-server-ip:5000"
    }

    private val client = OkHttpClient.Builder()
        .connectTimeout(10, java.util.concurrent.TimeUnit.SECONDS)
        .readTimeout(10, java.util.concurrent.TimeUnit.SECONDS)
        .writeTimeout(10, java.util.concurrent.TimeUnit.SECONDS)
        .build()

    // =========================
    // 获取异常信息
    // =========================

    fun getAlerts(
        username: String,
        callback: (List<Alert>) -> Unit
    ) {

        val url = "$BASE_URL/get_alerts?username=$username"

        val request = Request.Builder()
            .url(url)
            .build()

        client.newCall(request).enqueue(object : Callback {

            override fun onFailure(
                call: Call,
                e: IOException
            ) {

                Log.e(
                    "API_DEBUG",
                    "getAlerts失败: ${e.message}"
                )

                callback(emptyList())
            }

            override fun onResponse(
                call: Call,
                response: Response
            ) {

                val json =
                    response.body?.string() ?: ""

                Log.e(
                    "API_DEBUG",
                    json
                )

                val list = mutableListOf<Alert>()

                if (!json.trim().startsWith("[")) {

                    callback(emptyList())

                    return
                }

                val array = JSONArray(json)

                for (i in 0 until array.length()) {

                    val obj = array.getJSONObject(i)

                    list.add(
                        Alert(
                            obj.getInt("id"),
                            obj.getString("group_id"),
                            obj.getString("room"),
                            obj.getString("message"),
                            obj.getString("time"),
                            if (obj.isNull("state")) {
                                null
                            } else {
                                obj.getInt("state")
                            },
                            obj.optString("note", "")
                        )
                    )
                }

                callback(list)
            }
        })
    }

    // =========================
    // NFC绑定
    // =========================

    fun bindNFC(
        username: String,
        uid: String,
        callback: (Boolean, String, String?) -> Unit
    ) {

        val json = JSONObject()

        json.put("username", username)
        json.put("uid", uid)

        val body = json.toString()
            .toRequestBody(
                "application/json".toMediaType()
            )

        val request = Request.Builder()
            .url("$BASE_URL/bind_nfc")
            .post(body)
            .build()

        client.newCall(request).enqueue(object : Callback {

            override fun onFailure(call: Call, e: IOException) {

                callback(false, "网络错误", null)
            }

            override fun onResponse(call: Call, response: Response) {

                try {

                    val result = response.body?.string() ?: ""

                    val obj = JSONObject(result)

                    val success = obj.getBoolean("success")

                    val message = obj.getString("message")

                    val areaName =
                        if (obj.has("area_name"))
                            obj.getString("area_name")
                        else
                            null

                    callback(success, message, areaName)

                } catch (e: Exception) {

                    callback(false, "解析失败", null)
                }
            }
        })
    }

    fun unbindNFC(
        username: String,
        callback: (Boolean, String) -> Unit
    ) {

        val json = JSONObject()

        json.put("username", username)

        val body = json.toString()
            .toRequestBody(
                "application/json".toMediaType()
            )

        val request = Request.Builder()
            .url("$BASE_URL/unbind_nfc")
            .post(body)
            .build()

        client.newCall(request).enqueue(object : Callback {

            override fun onFailure(
                call: Call,
                e: IOException
            ) {

                callback(
                    false,
                    "网络错误"
                )
            }

            override fun onResponse(
                call: Call,
                response: Response
            ) {

                try {

                    val result =
                        response.body?.string() ?: ""

                    val obj =
                        JSONObject(result)

                    callback(
                        obj.getBoolean("success"),
                        obj.getString("message")
                    )

                } catch (e: Exception) {

                    callback(
                        false,
                        "解析失败"
                    )
                }
            }
        })
    }

    fun getCurrentArea(
        username: String,
        callback: (String?) -> Unit
    ) {

        val request = Request.Builder()
            .url(
                "$BASE_URL/get_current_area?username=$username"
            )
            .build()

        client.newCall(request)
            .enqueue(object : Callback {

                override fun onFailure(
                    call: Call,
                    e: IOException
                ) {

                    callback(null)
                }

                override fun onResponse(
                    call: Call,
                    response: Response
                ) {

                    try {

                        val result =
                            response.body?.string() ?: ""

                        val obj =
                            JSONObject(result)

                        if (
                            obj.getBoolean("success")
                        ) {

                            if (
                                obj.isNull("area_name")
                            ) {

                                callback(null)

                            } else {

                                callback(
                                    obj.getString(
                                        "area_name"
                                    )
                                )
                            }

                        } else {

                            callback(null)
                        }

                    } catch (e: Exception) {

                        callback(null)
                    }
                }
            })
    }

    fun verifyPassword(
        username: String,
        password: String,
        callback: (Boolean, String) -> Unit
    ) {

        val json = JSONObject()

        json.put("username", username)
        json.put("password", password)

        val body = json.toString()
            .toRequestBody(
                "application/json".toMediaType()
            )

        val request = Request.Builder()
            .url("$BASE_URL/verify_password")
            .post(body)
            .build()

        client.newCall(request)
            .enqueue(object : Callback {

                override fun onFailure(
                    call: Call,
                    e: IOException
                ) {

                    callback(false, "网络错误")
                }

                override fun onResponse(
                    call: Call,
                    response: Response
                ) {

                    try {

                        val result =
                            response.body?.string() ?: ""

                        val obj =
                            JSONObject(result)

                        callback(
                            obj.getBoolean("success"),
                            obj.getString("message")
                        )

                    } catch (e: Exception) {

                        callback(
                            false,
                            "解析失败"
                        )
                    }
                }
            })
    }

    fun changePassword(
        username: String,
        newPassword: String,
        callback: (Boolean, String) -> Unit
    ) {

        val json = JSONObject()

        json.put("username", username)
        json.put("new_password", newPassword)

        val body = json.toString()
            .toRequestBody(
                "application/json".toMediaType()
            )

        val request = Request.Builder()
            .url("$BASE_URL/change_password")
            .post(body)
            .build()

        client.newCall(request)
            .enqueue(object : Callback {

                override fun onFailure(
                    call: Call,
                    e: IOException
                ) {

                    callback(false, "网络错误")
                }

                override fun onResponse(
                    call: Call,
                    response: Response
                ) {

                    try {

                        val result =
                            response.body?.string() ?: ""

                        val obj =
                            JSONObject(result)

                        callback(
                            obj.getBoolean("success"),
                            obj.getString("message")
                        )

                    } catch (e: Exception) {

                        callback(false, "解析失败")
                    }
                }
            })
    }

    fun updateAlertState(
        id: Int,
        state: Int?,
        callback: (Boolean) -> Unit
    ) {

        val json = JSONObject().apply {
            put("id", id)
            put("state", state)
        }

        val body = json.toString()
            .toRequestBody("application/json".toMediaType())

        val request = Request.Builder()
            .url("$BASE_URL/update_alert_state")
            .post(body)
            .build()

        client.newCall(request).enqueue(object : Callback {

            override fun onFailure(call: Call, e: IOException) {
                callback(false)
            }

            override fun onResponse(call: Call, response: Response) {
                callback(response.isSuccessful)
            }
        })
    }

    // =========================
    // 更新事件备注
    // =========================

    fun updateNote(
        eventId: Int,
        note: String,
        callback: (Boolean, String) -> Unit
    ) {
        val json = JSONObject()
        json.put("id", eventId)
        json.put("note", note)

        val body = json.toString()
            .toRequestBody("application/json".toMediaType())

        val request = Request.Builder()
            .url("$BASE_URL/update_note")
            .post(body)
            .build()

        client.newCall(request).enqueue(object : Callback {
            override fun onFailure(call: Call, e: IOException) {
                callback(false, "网络连接失败")
            }

            override fun onResponse(call: Call, response: Response) {
                val result = response.body?.string() ?: ""
                try {
                    val obj = JSONObject(result)
                    callback(obj.optBoolean("success"), obj.optString("message", ""))
                } catch (e: Exception) {
                    callback(false, "服务器响应异常")
                }
            }
        })
    }
}