from django.test import SimpleTestCase
from django.urls import reverse


class RoutingTests(SimpleTestCase):
    def test_home_page_is_available(self):
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)

    def test_api_state_endpoint_is_available(self):
        response = self.client.get('/api/state')
        self.assertEqual(response.status_code, 200)
