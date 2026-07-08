from __future__ import annotations

from flask import Blueprint, g, redirect, render_template, request, url_for

from app.services.auth import authenticate, get_next_url, login_user, logout_user


bp = Blueprint("auth", __name__)


@bp.get("/login")
def login():  # type: ignore[no-untyped-def]
    if getattr(g, "user", None) is not None:
        return redirect(url_for("admin.dashboard"))
    return render_template("auth/login.html", error=None)


@bp.post("/login")
def login_post():  # type: ignore[no-untyped-def]
    if getattr(g, "user", None) is not None:
        return redirect(url_for("admin.dashboard"))

    username = (request.form.get("username") or "").strip()
    password = request.form.get("password") or ""

    if not (1 <= len(username) <= 64):
        return render_template("auth/login.html", error="用户名长度不合法")
    if not (1 <= len(password) <= 128):
        return render_template("auth/login.html", error="密码长度不合法")

    user = authenticate(username, password)
    if not user:
        return render_template("auth/login.html", error="用户名或密码错误")

    login_user(user)
    return redirect(get_next_url("admin.dashboard"))


@bp.get("/logout")
def logout():  # type: ignore[no-untyped-def]
    logout_user()
    return redirect(url_for("auth.login"))
