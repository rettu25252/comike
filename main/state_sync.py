import json
import sqlite3

from django.conf import settings
from django.db import connection, transaction
from django.utils.dateparse import parse_datetime
from django.utils import timezone

from .models import AppUserRecord, ItemRecord, RoomRecord, ShoppingListRecord


def ensure_catalog_tables():
    models = [AppUserRecord, RoomRecord, ShoppingListRecord, ItemRecord]
    existing = set(connection.introspection.table_names())

    def model_columns(model):
        return {
            field.column
            for field in model._meta.local_concrete_fields
            if field.column
        }

    def table_columns(table_name):
        with connection.cursor() as cursor:
            description = connection.introspection.get_table_description(cursor, table_name)
        return {col.name for col in description}

    should_rebuild = False
    for model in models:
        table_name = model._meta.db_table
        if table_name not in existing:
            should_rebuild = True
            break
        if not model_columns(model).issubset(table_columns(table_name)):
            should_rebuild = True
            break

    if not should_rebuild:
        return

    with connection.schema_editor() as editor:
        for model in [ItemRecord, ShoppingListRecord, RoomRecord, AppUserRecord]:
            table_name = model._meta.db_table
            if table_name in existing:
                editor.delete_model(model)
                existing.remove(table_name)
        for model in models:
            editor.create_model(model)
            existing.add(model._meta.db_table)


def _parse_created_at(value):
    if not value:
        return None
    parsed = parse_datetime(str(value))
    if parsed is None:
        return None
    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed, timezone.get_current_timezone())
    return parsed


def _normalize_status(item):
    raw = str(item.get("purchaseStatus") or "").strip()
    if raw in {"buying", "partial"}:
        return "buying"
    if raw == "done" or bool(item.get("purchased")):
        return "done"
    return "todo"


def _username(value):
    name = str(value or "").strip()
    return name or None


def sync_catalog_from_state(state):
    ensure_catalog_tables()
    state = state or {}
    lists = state.get("lists") or []
    users = set()

    top_username = _username(state.get("username"))
    if top_username:
        users.add(top_username)

    for list_entry in lists:
        created_by = _username(list_entry.get("createdByUsername"))
        if created_by:
            users.add(created_by)
        for item in list_entry.get("items") or []:
            updated_by = _username(item.get("updatedBy"))
            if updated_by:
                users.add(updated_by)

    with transaction.atomic():
        ItemRecord.objects.all().delete()
        ShoppingListRecord.objects.all().delete()
        RoomRecord.objects.all().delete()
        AppUserRecord.objects.all().delete()

        user_map = {
            username: AppUserRecord.objects.create(username=username)
            for username in sorted(users)
        }

        room_map = {}
        default_room_password = str(state.get("password") or "")
        default_admin_password = str(state.get("adminPassword") or "")

        for list_entry in lists:
            room_password = str(list_entry.get("roomPassword") or default_room_password or "")
            admin_password = str(list_entry.get("adminPassword") or default_admin_password or "")
            room_key = f"{room_password}::{admin_password}"

            if room_key not in room_map:
                created_by = user_map.get(_username(list_entry.get("createdByUsername")))
                room_map[room_key] = RoomRecord.objects.create(
                    room_key=room_key,
                    room_password=room_password,
                    admin_password=admin_password,
                    created_by=created_by,
                    created_at=_parse_created_at(list_entry.get("createdAt")),
                )

            list_source_id = str(list_entry.get("id") or "")
            if not list_source_id:
                continue

            shopping_list = ShoppingListRecord.objects.create(
                source_list_id=list_source_id,
                name=str(list_entry.get("name") or "名称なし"),
                room=room_map[room_key],
                created_by=user_map.get(_username(list_entry.get("createdByUsername"))),
                created_at=_parse_created_at(list_entry.get("createdAt")),
            )

            for item in list_entry.get("items") or []:
                source_item_id = str(item.get("id") or "")
                if not source_item_id:
                    continue
                status = _normalize_status(item)
                ItemRecord.objects.create(
                    source_item_id=source_item_id,
                    shopping_list=shopping_list,
                    name=str(item.get("name") or "名称なし"),
                    price=str(item.get("price") or ""),
                    memo=str(item.get("memo") or ""),
                    location=str(item.get("location") or ""),
                    position=str(item.get("position") or ""),
                    priority=str(item.get("priority") or ""),
                    purchase_status=status,
                    purchased=status == "done",
                    updated_by=user_map.get(_username(item.get("updatedBy"))),
                )


def sync_catalog_from_db():
    db_path = settings.BASE_DIR / "shopping_list.db"
    with sqlite3.connect(db_path) as connection:
        row = connection.execute("SELECT state_text FROM app_state WHERE id = 1").fetchone()
    if not row:
        sync_catalog_from_state({})
        return
    try:
        state = json.loads(row[0]) if row[0] else {}
    except json.JSONDecodeError:
        state = {}
    sync_catalog_from_state(state)