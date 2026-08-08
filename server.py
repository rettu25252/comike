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
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, unquote_plus

ROOT = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(ROOT, "shopping_list.db")
STATE_LOCK = threading.Lock()
NONCE_LOCK = threading.Lock()
ADMIN_USERNAME = "owner"
ADMIN_PASSWORD_ENV = "SHOPPING_ADMIN_PASSWORD"
SESSION_SECRET_ENV = "SHOPPING_SESSION_SECRET"
SESSION_NONCES = {}


def _read_env_secret(name, fallback):
    value = os.environ.get(name)
    if value:
        return value
    return fallback


ADMIN_PASSWORD = _read_env_secret(ADMIN_PASSWORD_ENV, "ishirettu25252")
SESSION_SECRET = _read_env_secret(SESSION_SECRET_ENV, "replace-this-secret")
ADMIN_PASSWORD_HASH = None


def get_admin_password_hash():
    global ADMIN_PASSWORD_HASH, ADMIN_PASSWORD
    password = _read_env_secret(ADMIN_PASSWORD_ENV, ADMIN_PASSWORD)
    if ADMIN_PASSWORD != password:
        ADMIN_PASSWORD = password
        ADMIN_PASSWORD_HASH = hash_password(password)
    elif ADMIN_PASSWORD_HASH is None:
        ADMIN_PASSWORD_HASH = hash_password(password)
    return ADMIN_PASSWORD_HASH


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


ADMIN_PASSWORD_HASH = get_admin_password_hash()


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
                f"<li><strong>{escape(str(item.get('name', '名称なし')))}</strong> — {escape(str(item.get('location', '')))} / {escape(str(item.get('position', '')))} / {escape(str(item.get('price', '')))}"
                f"<br/><span class=\"muted\">{escape(str(item.get('memo', '')))}</span></li>"
            )
        item_markup = "<ul>" + "".join(item_rows) + "</ul>" if item_rows else "<p class=\"muted\">アイテムなし</p>"
        room_password = list_entry.get("roomPassword") or state.get("password") or "未設定"
        admin_password = list_entry.get("adminPassword") or state.get("adminPassword") or "未設定"
        created_by_username = list_entry.get("createdByUsername") or state.get("username") or "未設定"
        created_at = list_entry.get("createdAt") or "未設定"
        list_cards.append(
            f"<div class=\"stat\"><strong>{escape(str(list_entry.get('name', '無名リスト')))}</strong><div>{len(items)}件</div><div style=\"margin-top:10px; padding:10px; border-radius:10px; background:#fff; border:1px solid #e2e8f0;\"><div><strong>部屋PW</strong>: {escape(str(room_password))}</div><div><strong>管理者PW</strong>: {escape(str(admin_password))}</div><div><strong>作成者</strong>: {escape(str(created_by_username))}</div><div><strong>作成日時</strong>: {escape(str(created_at))}</div></div>{item_markup}<form method=\"post\" action=\"/admin\" style=\"margin-top:8px;\"><input type=\"hidden\" name=\"action\" value=\"delete_list\" /><input type=\"hidden\" name=\"list_id\" value=\"{escape(str(list_entry.get('id', '')))}\" /><button class=\"danger\" type=\"submit\">削除</button></form></div>"
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
    <h2>新しいリストを追加</h2>
    <form method=\"post\" action=\"/admin\" style=\"display:grid; gap:12px; max-width:320px;\">
      <input type=\"hidden\" name=\"action\" value=\"create_list\" />
      <input type=\"text\" name=\"list_name\" placeholder=\"リスト名\" required />
      <button class=\"primary\" type=\"submit\">追加</button>
    </form>
    <h2 style=\"margin-top:24px;\">全リスト一覧</h2>
    <div class=\"grid\">{list_cards_markup}</div>
    """


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
            (json.dumps(payload.get("state")), int(payload.get("version", 0)))
        )
        connection.commit()


class ShoppingListHandler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/state":
            self.send_json(204, {})
            return
        self.send_json(404, {"error": "not found"})

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/state":
            with STATE_LOCK:
                payload = load_state()
            self.send_json(200, payload)
            return

        if parsed.path == "/admin":
            self.handle_admin_page()
            return

        if parsed.path == "/admin/login":
            self.send_login_form()
            return

        if parsed.path == "/":
            self.serve_file("index.html")
            return

        file_path = parsed.path.lstrip("/")
        if file_path in {"", "."}:
            file_path = "index.html"
        self.serve_file(file_path)

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path == "/admin/login":
            self.handle_admin_login()
            return
        if parsed.path == "/admin/logout":
            self.handle_admin_logout()
            return
        if parsed.path == "/admin":
            self.handle_admin_post()
            return
        self.send_json(405, {"error": "method not allowed"})

    def do_PUT(self):
        parsed = urlparse(self.path)
        if parsed.path != "/api/state":
            self.send_json(404, {"error": "not found"})
            return

        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length).decode("utf-8")
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            self.send_json(400, {"error": "invalid json"})
            return

        with STATE_LOCK:
            current = load_state()
            current_version = int(current.get("version", 0))
            incoming_version = int(payload.get("version", 0))
            state_payload = payload.get("state") or {}

            if incoming_version != current_version:
                self.send_json(409, {
                    "error": "conflict",
                    "state": current.get("state"),
                    "version": current_version,
                })
                return

            new_version = current_version + 1
            new_state = {"state": state_payload, "version": new_version}
            save_state(new_state)
            self.send_json(200, new_state)

    def handle_admin_login(self):
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length).decode("utf-8")
        data = {}
        for part in body.split("&"):
            if "=" in part:
                key, value = part.split("=", 1)
                data[key] = unquote_plus(value)
        password = data.get("password", "")
        nonce = data.get("nonce", "")
        if not consume_login_nonce(nonce):
            self.send_response(403)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(b"<html><body><h1>Invalid login request</h1></body></html>")
            return
        password_hash = get_admin_password_hash()
        if verify_password(password, password_hash):
            token = create_session_token(ADMIN_USERNAME, SESSION_SECRET)
            self.send_response(303)
            self.send_header("Location", "/admin")
            self.send_header("Set-Cookie", f"admin_session={token}; HttpOnly; SameSite=Lax; Path=/; Max-Age=1800")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            return
        self.send_response(401)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(b"<html><body><h1>Unauthorized</h1></body></html>")

    def handle_admin_logout(self):
        self.send_response(303)
        self.send_header("Location", "/admin/login")
        self.send_header("Set-Cookie", "admin_session=; HttpOnly; SameSite=Lax; Path=/; Max-Age=0")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

    def handle_admin_post(self):
        cookie = self.headers.get("Cookie", "")
        token = None
        for item in cookie.split(";"):
            if item.strip().startswith("admin_session="):
                token = item.split("=", 1)[1].strip()
                break
        if not token or not validate_session_token(token, SESSION_SECRET):
            self.send_response(303)
            self.send_header("Location", "/admin/login")
            self.end_headers()
            return

        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length).decode("utf-8")
        data = {}
        for part in body.split("&"):
            if "=" in part:
                key, value = part.split("=", 1)
                data[key] = unquote_plus(value)

        action = data.get("action", "")
        with STATE_LOCK:
            current = load_state()
            state_payload = current.get("state") or {}
            lists = state_payload.get("lists") or []
            if action == "create_list":
                name = (data.get("list_name") or "").strip()
                if name:
                    lists.append({
                        "id": f"list-{int(time.time() * 1000)}",
                        "name": name,
                        "items": [],
                        "locations": [],
                        "roomPassword": state_payload.get("password", ""),
                        "adminPassword": state_payload.get("adminPassword", ""),
                        "createdByUsername": state_payload.get("username", ""),
                        "createdAt": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
                    })
                    state_payload["lists"] = lists
                    save_state({"state": state_payload, "version": int(current.get("version", 0)) + 1})
            elif action == "delete_list":
                list_id = data.get("list_id", "")
                state_payload["lists"] = [entry for entry in lists if entry.get("id") != list_id]
                save_state({"state": state_payload, "version": int(current.get("version", 0)) + 1})

        self.send_response(303)
        self.send_header("Location", "/admin")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

    def handle_admin_page(self):
        cookie = self.headers.get("Cookie", "")
        token = None
        for item in cookie.split(";"):
            if item.strip().startswith("admin_session="):
                token = item.split("=", 1)[1].strip()
                break
        if not token or not validate_session_token(token, SESSION_SECRET):
            self.send_response(303)
            self.send_header("Location", "/admin/login")
            self.end_headers()
            return
        html = open(os.path.join(ROOT, "admin.html"), "r", encoding="utf-8").read().replace("{{ADMIN_CONTENT}}", build_admin_page_content())
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        self.end_headers()
        self.wfile.write(body)

    def send_login_form(self):
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
        body = form.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        self.end_headers()
        self.wfile.write(body)

    def serve_file(self, relative_path):
        file_path = os.path.join(ROOT, relative_path)
        if not os.path.exists(file_path) or not os.path.isfile(file_path):
            self.send_json(404, {"error": "not found"})
            return

        content_type = "text/html; charset=utf-8"
        if relative_path.endswith(".css"):
            content_type = "text/css; charset=utf-8"
        elif relative_path.endswith(".js"):
            content_type = "application/javascript; charset=utf-8"

        with open(file_path, "rb") as handle:
            body = handle.read()

        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_json(self, status, payload):
        data = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, PUT, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format, *args):
        return


if __name__ == "__main__":
    server = ThreadingHTTPServer(("127.0.0.1", 8000), ShoppingListHandler)
    print("Server running on http://127.0.0.1:8000")
    server.serve_forever()
