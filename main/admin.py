from django.contrib import admin

from .models import AppUserRecord, ItemRecord, RoomRecord, ShoppingListRecord

admin.site.register(AppUserRecord)
admin.site.register(RoomRecord)
admin.site.register(ShoppingListRecord)
admin.site.register(ItemRecord)