from django.contrib import admin
from django.urls import path

from . import views

urlpatterns = [
    path("admin/catalog-diagnostics", views.admin_catalog_diagnostics, name="admin_catalog_diagnostics"),
    path("admin/", admin.site.urls),
    path("api/state", views.api_state, name="api_state"),
    path("assets/<path:filename>", views.serve_asset, name="serve_asset"),
    path("styles.css", views.serve_asset, {"filename": "styles.css"}, name="styles"),
    path("app.js", views.serve_asset, {"filename": "app.js"}, name="app_js"),
    path("<str:list_id>/", views.home, name="home_with_list"),
    path("", views.home, name="home"),
]
