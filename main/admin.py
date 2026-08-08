from django.contrib import admin

from .models import AppUserRecord, ItemRecord, RoomRecord, ShoppingListRecord
from .state_sync import ensure_catalog_tables


class SelfHealingAdminMixin:
    def get_queryset(self, request):
        ensure_catalog_tables()
        return super().get_queryset(request)


@admin.register(AppUserRecord)
class AppUserRecordAdmin(SelfHealingAdminMixin, admin.ModelAdmin):
    list_display = ("username", "created_at")
    search_fields = ("username",)
    ordering = ("username",)


@admin.register(RoomRecord)
class RoomRecordAdmin(SelfHealingAdminMixin, admin.ModelAdmin):
    list_display = ("room_password", "admin_password", "created_by", "created_at")
    search_fields = ("room_password", "admin_password", "created_by__username")
    list_filter = ("created_at",)
    autocomplete_fields = ("created_by",)


@admin.register(ShoppingListRecord)
class ShoppingListRecordAdmin(SelfHealingAdminMixin, admin.ModelAdmin):
    list_display = ("name", "source_list_id", "room", "created_by", "created_at")
    search_fields = ("name", "source_list_id", "room__room_password", "created_by__username")
    list_filter = ("created_at",)
    autocomplete_fields = ("room", "created_by")


@admin.register(ItemRecord)
class ItemRecordAdmin(SelfHealingAdminMixin, admin.ModelAdmin):
    list_display = (
        "name",
        "shopping_list",
        "location",
        "position",
        "priority",
        "purchase_status",
        "purchased",
        "updated_by",
    )
    search_fields = (
        "name",
        "shopping_list__name",
        "location",
        "position",
        "memo",
        "updated_by__username",
    )
    list_filter = ("purchase_status", "purchased", "priority")
    autocomplete_fields = ("shopping_list", "updated_by")