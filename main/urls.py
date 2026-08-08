from django.urls import path

from . import views

urlpatterns = [
    path("admin/login", views.admin_login, name="admin_login"),
    path("admin/login/", views.admin_login, name="admin_login_slash"),
    path("admin/logout", views.admin_logout, name="admin_logout"),
    path("admin/logout/", views.admin_logout, name="admin_logout_slash"),
    path("admin", views.admin_page, name="admin_page"),
    path("admin/", views.admin_page, name="admin_page_slash"),
    path("api/state", views.api_state, name="api_state"),
    path("assets/<path:filename>", views.serve_asset, name="serve_asset"),
    path("styles.css", views.serve_asset, {"filename": "styles.css"}, name="styles"),
    path("app.js", views.serve_asset, {"filename": "app.js"}, name="app_js"),
    path("<str:list_id>/", views.home, name="home_with_list"),
    path("", views.home, name="home"),
]
