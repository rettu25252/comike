import json
import sqlite3
from pathlib import Path

from django.conf import settings
from django.http import Http404, HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = settings.BASE_DIR / "shopping_list.db"


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
