from django.db import models


class AppUserRecord(models.Model):
    username = models.CharField(max_length=150, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["username"]
        verbose_name = "ユーザー"
        verbose_name_plural = "ユーザー"

    def __str__(self):
        return self.username


class RoomRecord(models.Model):
    room_key = models.CharField(max_length=512, unique=True)
    room_password = models.CharField(max_length=255, blank=True, default="")
    admin_password = models.CharField(max_length=255, blank=True, default="")
    created_by = models.ForeignKey(
        AppUserRecord,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="created_rooms",
    )
    created_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["room_password", "id"]
        verbose_name = "部屋"
        verbose_name_plural = "部屋"

    def __str__(self):
        return self.room_password or f"room-{self.id}"


class ShoppingListRecord(models.Model):
    source_list_id = models.CharField(max_length=255, unique=True)
    name = models.CharField(max_length=255)
    room = models.ForeignKey(
        RoomRecord,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="lists",
    )
    created_by = models.ForeignKey(
        AppUserRecord,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="created_lists",
    )
    created_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["name", "id"]
        verbose_name = "リスト"
        verbose_name_plural = "リスト"

    def __str__(self):
        return self.name


class ItemRecord(models.Model):
    source_item_id = models.CharField(max_length=255)
    shopping_list = models.ForeignKey(
        ShoppingListRecord,
        on_delete=models.CASCADE,
        related_name="items",
    )
    name = models.CharField(max_length=255)
    price = models.CharField(max_length=255, blank=True, default="")
    memo = models.TextField(blank=True, default="")
    location = models.CharField(max_length=255, blank=True, default="")
    position = models.CharField(max_length=255, blank=True, default="")
    priority = models.CharField(max_length=64, blank=True, default="")
    purchase_status = models.CharField(max_length=32, blank=True, default="todo")
    purchased = models.BooleanField(default=False)
    updated_by = models.ForeignKey(
        AppUserRecord,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="updated_items",
    )

    class Meta:
        ordering = ["shopping_list__name", "position", "name", "id"]
        verbose_name = "アイテム"
        verbose_name_plural = "アイテム"
        unique_together = [("shopping_list", "source_item_id")]

    def __str__(self):
        return self.name