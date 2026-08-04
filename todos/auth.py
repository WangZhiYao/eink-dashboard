import base64
import secrets

from fastapi import HTTPException, Request


def verify_admin(request: Request) -> None:
    """Require HTTP Basic auth with username == ADMIN_USERNAME and
    password == ADMIN_PASSWORD (both constant-time compared). Used for both the
    REST API (automation: `curl -u user:pass`) and the web UI (browser-native
    Basic auth, cached by the browser)."""
    from config import settings

    auth_header = request.headers.get("authorization", "")
    if auth_header.lower().startswith("basic "):
        try:
            decoded = base64.b64decode(auth_header[6:]).decode()
            user, sep, password = decoded.partition(":")
            if (sep
                    and secrets.compare_digest(user, settings.admin_username)
                    and secrets.compare_digest(password, settings.admin_password)):
                return
        except Exception:
            pass
    raise HTTPException(
        status_code=401,
        detail="unauthorized",
        headers={"WWW-Authenticate": 'Basic realm="todos"'},
    )
