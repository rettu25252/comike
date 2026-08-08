import unittest

from django.test import SimpleTestCase
from django.urls import resolve

from main import urls as main_urls
from server import build_admin_page_content, create_session_token, get_admin_password_hash, hash_password, validate_session_token, verify_password


class AdminUrlTests(SimpleTestCase):
    def test_admin_routes_resolve_with_trailing_slashes(self):
        self.assertIn(resolve("/admin/", urlconf=main_urls).view_name, {"admin_page", "admin_page_slash"})
        self.assertIn(resolve("/admin/login/", urlconf=main_urls).view_name, {"admin_login", "admin_login_slash"})
        self.assertIn(resolve("/admin/logout/", urlconf=main_urls).view_name, {"admin_logout", "admin_logout_slash"})


class AdminAuthTests(unittest.TestCase):
    def test_password_hash_roundtrip(self):
        hashed = hash_password("very-strong-password")
        self.assertTrue(verify_password("very-strong-password", hashed))
        self.assertFalse(verify_password("wrong-password", hashed))

    def test_current_admin_password_is_accepted(self):
        hashed = get_admin_password_hash()
        self.assertTrue(verify_password("ishirettu25252", hashed))

    def test_admin_page_contains_global_management_controls(self):
        html = build_admin_page_content()
        self.assertIn("全体管理", html)
        self.assertIn("新しいリストを追加", html)
        self.assertIn("削除", html)

    def test_session_token_roundtrip(self):
        token = create_session_token("owner", "test-secret")
        payload = validate_session_token(token, "test-secret")
        self.assertEqual(payload["username"], "owner")
        self.assertIsNone(validate_session_token("not-a-valid-token", "test-secret"))


if __name__ == "__main__":
    unittest.main()
