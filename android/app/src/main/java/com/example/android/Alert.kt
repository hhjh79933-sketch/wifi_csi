package com.example.android

import java.io.Serializable

data class Alert(
    val id: Int,
    val group_id: String,
    val room: String,
    val message: String,
    val time: String,
    var state: Int?,
    val note: String = ""
) : Serializable