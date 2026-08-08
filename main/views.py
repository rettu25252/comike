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


def build_admin_page_content():
    state = load_state().get("state") or {}
    lists = state.get("lists") or []
    total_items = sum(len(list_entry.get("items") or []) for list_entry in lists)
    list_cards = []
    for list_entry in lists:
        items = list_entry.get("items") or []
        item_rows = []
        for item in items:
            item_rows.append(
                f"<li><strong>{escape(str(item.get('name', '名称なし')))}</strong> — {escape(str(item.get('location', '')))} / {escape(str(item.get('position', '')))} / {escape(str(item.get('price', '')))}<br/><span class=\"muted\">{escape(str(item.get('memo', '')))}</span></li>"
            )
        item_markup = "<ul>" + "".join(item_rows) + "</ul>" if item_rows else "<p class=\"muted\">アイテムなし</p>"
        room_password = list_entry.get("roomPassword") or state.get("password") or "未設定"
        admin_password = list_entry.get("adminPassword") or state.get("adminPassword") or "未設定"
        created_by_username = list_entry.get("createdByUsername") or state.get("username") or "未設定"
        created_at = list_entry.get("createdAt") or "未設定"
        list_cards.append(
            f"<div class=\"stat\"><strong>{escape(str(list_entry.get('name', '無名リスト')))}</strong><div>{len(items)}件</div><div style=\"margin-top:10px; padding:10px; border-radius:10px; background:#fff; border:1px solid #e2e8f0;\"><div><strong>部屋PW</strong>: {escape(str(room_password))}</div><div><strong>管理者PW</strong>: {escape(str(admin_password))}</div><div><strong>作成者</strong>: {escape(str(created_by_username))}</div><div><strong>作成日時</strong>: {escape(str(created_at))}</div></div>{item_markup}</div>"
        )
    list_cards_markup = "".join(list_cards) if list_cards else "<p class=\"muted\">まだリストはありません。</p>"
    return f"""
    <h1>全体管理ページ</h1>
    <p class=\"muted\">このページはサイト管理者の私だけが使用します。全リスト、全アイテムの閲覧・追加・削除を行えます。</p>
    <div class=\"stats\">
      <div class=\"stat\"><strong>リスト数</strong><div>{len(lists)}</div></div>
      <div class=\"stat\"><strong>アイテム数</strong><div>{total_items}</div></div>
      <div class=\"stat\"><strong>状態</strong><div>{'設定済み' if state else '未設定'}</div></div>
    </div>
    <div class=\"actions\">
      <a href=\"/\" style=\"text-decoration:none;\"><button class=\"secondary\" type=\"button\">一覧へ戻る</button></a>
      <form method=\"post\" action=\"/admin/logout\" style=\"display:inline;\">
        <button class=\"danger\" type=\"submit\">ログアウト</button>
      </form>
    </div>
    <hr />
    <h2>全リスト一覧</h2>
    <div class=\"grid\">{list_cards_markup}</div>
    """


@csrf_exempt
def admin_login(request):
    if request.method == "GET":
        nonce = generate_login_nonce()
        form = f"""
        <html><body style=\"font-family: sans-serif; padding: 24px;\">
          <h1>管理者ログイン</h1>
          <form method=\"post\" action=\"/admin/login\">
            <input type=\"hidden\" name=\"nonce\" value=\"{nonce}\" />
            <label>管理者パスワード</label><br/>
            <input type=\"password\" name=\"password\" required style=\"width: 100%; max-width: 320px; padding: 8px; margin: 8px 0;\" /><br/>
            <button type=\"submit\">ログイン</button>
          </form>
        </body></html>
        """
        return HttpResponse(form, content_type="text/html; charset=utf-8")

    if request.method == "POST":
        body = request.POST
        password = body.get("password", "")
        nonce = body.get("nonce", "")
        if not consume_login_nonce(nonce):
            return HttpResponse("Invalid login request", status=403, content_type="text/html; charset=utf-8")
        if verify_password(password, ADMIN_PASSWORD_HASH):
            token = create_session_token(ADMIN_USERNAME, SESSION_SECRET)
            response = HttpResponse(status=302)
            response["Location"] = "/admin"
            response.set_cookie("admin_session", token, httponly=True, samesite="Lax", max_age=1800)
            return response
        return HttpResponse("Unauthorized", status=401, content_type="text/html; charset=utf-8")

    return HttpResponse("Method not allowed", status=405, content_type="text/html; charset=utf-8")


@csrf_exempt
def admin_logout(request):
    response = HttpResponse(status=302)
    response["Location"] = "/admin/login"
    response.delete_cookie("admin_session")
    return response


@csrf_exempt
def admin_page(request):
    token = request.COOKIES.get("admin_session")
    if not token or not validate_session_token(token, SESSION_SECRET):
        response = HttpResponse(status=302)
        response["Location"] = "/admin/login"
        return response

    html = f"""
    <!DOCTYPE html>
    <html lang=\"ja\">
      <head>
        <meta charset=\"UTF-8\" />
        <meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\" />
        <title>管理者ページ</title>
        <style>
          :root {{ color-scheme: light; font-family: \"Yu Gothic UI\", \"Segoe UI\", sans-serif; --bg: #0f172a; --panel: #ffffff; --text: #0f172a; --muted: #64748b; --accent: #2563eb; --danger: #dc2626; --border: #e2e8f0; }}
          body {{ margin: 0; background: linear-gradient(135deg, #eff6ff 0%, #f8fafc 100%); color: var(--text); }}
          .shell {{ max-width: 860px; margin: 0 auto; padding: 24px; }}
          .card {{ background: var(--panel); border: 1px solid var(--border); border-radius: 20px; padding: 24px; box-shadow: 0 20px 45px rgba(15, 23, 42, 0.08); }}
          h1, h2, p {{ margin-top: 0; }}
          .grid {{ display: grid; gap: 12px; }}
          .stats {{ display: grid; gap: 10px; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); margin-top: 16px; }}
          .stat {{ border: 1px solid var(--border); border-radius: 14px; padding: 12px; background: #f8fafc; }}
          .actions {{ display: flex; gap: 10px; flex-wrap: wrap; margin-top: 16px; }}
          button {{ border: 0; border-radius: 999px; padding: 10px 14px; cursor: pointer; min-height: 44px; font-weight: 700; }}
          .secondary {{ background: #eff6ff; color: var(--accent); }}
          .danger {{ background: #fee2e2; color: var(--danger); }}
          .muted {{ color: var(--muted); }}
        </style>
      </head>
      <body>
        <main class=\"shell\">
          <section class=\"card\">
            {build_admin_page_content()}
          </section>
        </main>
      </body>
    </html>
    """
    return HttpResponse(html, content_type="text/html; charset=utf-8")


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
