import unittest

from django.contrib.auth import authenticate
from django.test import Client, TestCase

from server import build_admin_page_content, create_session_token, get_admin_password_hash, hash_password, validate_session_token, verify_password


class AdminUrlTests(TestCase):
    def test_admin_root_redirects_to_the_standard_django_admin_login_page(self):
        client = Client()
        response = client.get("/admin/")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "/admin/login/?next=/admin/")

    def test_admin_login_page_is_available(self):
        client = Client()
        response = client.get("/admin/login/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Log in | Django site admin")

    def test_owner_bootstrap_backend_authenticates_owner(self):
        user = authenticate(username="owner", password="ishirettu25252")
        self.assertIsNotNone(user)
        self.assertEqual(user.username, "owner")


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
