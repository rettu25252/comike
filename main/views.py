import base64
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import threading
import time
from html import escape
from pathlib import Path

from django.conf import settings
from django.http import Http404, HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt

from .models import AppUserRecord, ItemRecord, RoomRecord, ShoppingListRecord
from .state_sync import ensure_catalog_tables, sync_catalog_from_db, sync_catalog_from_state

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = settings.BASE_DIR / "shopping_list.db"
STATE_LOCK = threading.Lock()
NONCE_LOCK = threading.Lock()
SESSION_NONCES = {}
ADMIN_USERNAME = "owner"
ADMIN_PASSWORD_ENV = "SHOPPING_ADMIN_PASSWORD"
SESSION_SECRET_ENV = "SHOPPING_SESSION_SECRET"


def _read_env_secret(name, fallback):
    value = os.environ.get(name)
    if value:
        return value
    return fallback


ADMIN_PASSWORD = _read_env_secret(ADMIN_PASSWORD_ENV, "ishirettu25252")
SESSION_SECRET = _read_env_secret(SESSION_SECRET_ENV, "replace-this-secret")


def hash_password(password):
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 200_000)
    return base64.b64encode(salt + digest).decode("ascii")


def verify_password(password, stored_hash):
    try:
        encoded = base64.b64decode(stored_hash.encode("ascii"))
    except Exception:
        return False
    salt = encoded[:16]
    digest = encoded[16:]
    check = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 200_000)
    return hmac.compare_digest(check, digest)


def create_session_token(username, secret):
    payload = json.dumps({"username": username, "exp": int(time.time()) + 1800}, separators=(",", ":"), ensure_ascii=False)
    signature = hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    return base64.urlsafe_b64encode(f"{payload}.{signature}".encode("utf-8")).decode("ascii")


def validate_session_token(token, secret):
    try:
        decoded = base64.urlsafe_b64decode(token.encode("ascii")).decode("utf-8")
    except Exception:
        return None
    try:
        payload, signature = decoded.split(".", 1)
    except ValueError:
        return None
    expected = hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        return None
    try:
        data = json.loads(payload)
    except Exception:
        return None
    if int(data.get("exp", 0)) < int(time.time()):
        return None
    return data


def generate_login_nonce():
    nonce = secrets.token_hex(16)
    with NONCE_LOCK:
        SESSION_NONCES[nonce] = int(time.time()) + 300
    return nonce


def consume_login_nonce(nonce):
    with NONCE_LOCK:
        if not nonce:
            return False
        if nonce not in SESSION_NONCES:
            return False
        del SESSION_NONCES[nonce]
        return True


ADMIN_PASSWORD_HASH = hash_password(ADMIN_PASSWORD)


def init_db():
    with sqlite3.connect(DB_PATH) as connection:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS app_state (id INTEGER PRIMARY KEY CHECK (id = 1), state_text TEXT NOT NULL, version INTEGER NOT NULL)"
        )
        connection.execute(
            "INSERT OR IGNORE INTO app_state (id, state_text, version) VALUES (1, '{}', 0)"
        )
        connection.commit()


def load_state():
    init_db()
    with sqlite3.connect(DB_PATH) as connection:
        row = connection.execute("SELECT state_text, version FROM app_state WHERE id = 1").fetchone()
        if not row:
            return {"state": None, "version": 0}
        try:
            state_payload = json.loads(row[0])
        except json.JSONDecodeError:
            state_payload = None
        return {"state": state_payload, "version": int(row[1])}


def save_state(payload):
    init_db()
    with sqlite3.connect(DB_PATH) as connection:
        connection.execute(
            "INSERT INTO app_state (id, state_text, version) VALUES (1, ?, ?) ON CONFLICT(id) DO UPDATE SET state_text = excluded.state_text, version = excluded.version",
            (json.dumps(payload.get("state")), int(payload.get("version", 0))),
        )
        connection.commit()


def home(request, list_id=None):
    index_path = ROOT / "index.html"
    if not index_path.exists():
        raise Http404("index.html not found")

    return HttpResponse(index_path.read_text(encoding="utf-8"), content_type="text/html; charset=utf-8")


@csrf_exempt
def api_state(request):
    if request.method == "OPTIONS":
        response = JsonResponse({}, status=204)
        response["Access-Control-Allow-Origin"] = "*"
        response["Access-Control-Allow-Methods"] = "GET, PUT, OPTIONS"
        response["Access-Control-Allow-Headers"] = "Content-Type"
        return response

    if request.method == "GET":
        try:
            ensure_catalog_tables()
            sync_catalog_from_db()
        except Exception:
            # Keep API available even if sync fails unexpectedly.
            pass
        payload = load_state()
        response = JsonResponse(payload)
        response["Access-Control-Allow-Origin"] = "*"
        return response

    if request.method == "PUT":
        if len(request.body) > 1_000_000:  # 1 MB limit
            return JsonResponse({"error": "payload too large"}, status=413)
        try:
            payload = json.loads(request.body.decode("utf-8"))
        except json.JSONDecodeError:
            return JsonResponse({"error": "invalid json"}, status=400)

        current = load_state()
        current_version = int(current.get("version", 0))
        incoming_version = int(payload.get("version", 0))
        state_payload = payload.get("state") or {}

        if incoming_version != current_version:
            response = JsonResponse(
                {"error": "conflict", "state": current.get("state"), "version": current_version},
                status=409,
            )
            response["Access-Control-Allow-Origin"] = "*"
            return response

        new_version = current_version + 1
        new_state = {"state": state_payload, "version": new_version}
        save_state(new_state)
        try:
            ensure_catalog_tables()
            sync_catalog_from_state(state_payload)
        except Exception:
            # Keep API write path resilient even when admin sync fails.
            pass
        response = JsonResponse(new_state)
        response["Access-Control-Allow-Origin"] = "*"
        return response

    return JsonResponse({"error": "method not allowed"}, status=405)


def serve_asset(request, filename):
    # restrict to known static files only to prevent path traversal
    allowed = {"styles.css", "app.js"}
    if filename not in allowed:
        raise Http404(f"{filename} not found")
    asset_path = ROOT / filename
    if not asset_path.exists() or not asset_path.is_file():
        raise Http404(f"{filename} not found")

    if filename.endswith(".css"):
        content_type = "text/css; charset=utf-8"
    elif filename.endswith(".js"):
        content_type = "application/javascript; charset=utf-8"
    else:
        content_type = "application/octet-stream"

    return HttpResponse(asset_path.read_bytes(), content_type=content_type)


def admin_catalog_diagnostics(request):
    if not request.user.is_authenticated or not request.user.is_staff:
        return JsonResponse({"error": "forbidden"}, status=403)

    result = {}
    try:
        ensure_catalog_tables()
        result["ensure_catalog_tables"] = "ok"
    except Exception as error:
        result["ensure_catalog_tables"] = f"error: {error!r}"

    models = {
        "users": AppUserRecord,
        "rooms": RoomRecord,
        "lists": ShoppingListRecord,
        "items": ItemRecord,
    }
    for key, model in models.items():
        try:
            result[key] = {
                "table": model._meta.db_table,
                "count": model.objects.count(),
            }
        except Exception as error:
            result[key] = {
                "table": model._meta.db_table,
                "error": repr(error),
            }

    return JsonResponse(result)
