from django.test import SimpleTestCase
from django.urls import reverse


class PwaServiceWorkerTests(SimpleTestCase):
    def test_service_worker_is_served_with_root_scope(self):
        response = self.client.get(reverse('service_worker'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Service-Worker-Allowed'], '/')
        self.assertEqual(response['Content-Type'], 'application/javascript')
        self.assertIn('no-cache', response['Cache-Control'])
