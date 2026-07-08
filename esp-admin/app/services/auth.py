from __future__ import annotations

from functools import wraps
from urllib.parse import urlparse

from flask import g, redirect, request, session, url_for

from app.models.user import User


def load_user_from_session() -> User | None:
    user_id = session.get("user_id")
    if not user_id:
        return None
    return User.query.get(int(user_id))


def login_user(user: User) -> None:
    session["user_id"] = user.id


def logout_user() -> None:
    session.pop("user_id", None)


def authenticate(username: str, password: str) -> User | None:
    user = User.query.filter_by(username=username).first()
    if not user:
        return None
    if not user.check_password(password):
        return None
    return user


def _is_safe_next_url(target: str) -> bool:
    if not target:
        return False
    ref_url = urlparse(request.host_url)
    test_url = urlparse(target)
    return (
        (not test_url.scheme)
        and (not test_url.netloc)
        and target.startswith("/")
        and ref_url.netloc == urlparse(request.host_url).netloc
    )


def login_required(view):  # type: ignore[no-untyped-def]
    @wraps(view)
    def wrapped(*args, **kwargs):  # type: ignore[no-untyped-def]
        if getattr(g, "user", None) is None:
            next_url = request.full_path if request.query_string else request.path
            return redirect(url_for("auth.login", next=next_url))
        return view(*args, **kwargs)

    return wrapped


def admin_required(view):  # type: ignore[no-untyped-def]
    @wraps(view)
    def wrapped(*args, **kwargs):  # type: ignore[no-untyped-def]
        user = getattr(g, "user", None)
        if user is None:
            next_url = request.full_path if request.query_string else request.path
            return redirect(url_for("auth.login", next=next_url))
        if not getattr(user, "is_admin", False):
            return redirect(url_for("auth.login"))
        return view(*args, **kwargs)

    return wrapped


def get_next_url(default_endpoint: str) -> str:
    target = request.args.get("next")
    if target and _is_safe_next_url(target):
        return target
    return url_for(default_endpoint)
