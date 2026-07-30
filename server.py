import json
import os
import sqlite3
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

ROOT = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(ROOT, "shopping_list.db")
STATE_LOCK = threading.Lock()


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

        if parsed.path == "/":
            self.serve_file("index.html")
            return

        file_path = parsed.path.lstrip("/")
        if file_path in {"", "."}:
            file_path = "index.html"
        self.serve_file(file_path)

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
