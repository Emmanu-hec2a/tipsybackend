from django.test import TestCase
from django.conf import settings
from urbanfoods.models import User, Store, PlatformConfig
from urbanfoods.mpesa_utils import encrypt_value, decrypt_value, MpesaIntegration
import os

class MpesaEncryptionTest(TestCase):
    def setUp(self):
        # Ensure we have a key for testing
        if not os.environ.get('ENCRYPTION_KEY'):
            os.environ['ENCRYPTION_KEY'] = '6csUuoMhN7dvrad3XaJ5ApYcFPV2AEFtlwSUEAzoREU='

    def test_encryption_roundtrip(self):
        original_value = "secret_consumer_key_123"
        encrypted = encrypt_value(original_value)
        self.assertNotEqual(original_value, encrypted)
        self.assertTrue(encrypted.startswith('gAAAA')) # Typical Fernet start
        
        decrypted = decrypt_value(encrypted)
        self.assertEqual(original_value, decrypted)

class MpesaIntegrationTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='teststore', password='password')
        self.store = Store.objects.create(
            owner=self.user,
            name="Test Store",
            mpesa_shortcode="174379",
            mpesa_consumer_key=encrypt_value("test_key"),
            mpesa_consumer_secret=encrypt_value("test_secret"),
            mpesa_passkey=encrypt_value("test_passkey")
        )

    def test_store_integration_initialization(self):
        integration = MpesaIntegration(store=self.store)
        self.assertEqual(integration.shortcode, "174379")
        self.assertEqual(integration.consumer_key, "test_key")
        self.assertEqual(integration.consumer_secret, "test_secret")
        self.assertEqual(integration.passkey, "test_passkey")

    def test_phone_formatting(self):
        integration = MpesaIntegration()
        self.assertEqual(integration.format_phone_number("0712345678"), "254712345678")
        self.assertEqual(integration.format_phone_number("254712345678"), "254712345678")
        self.assertEqual(integration.format_phone_number("712345678"), "254712345678")
        with self.assertRaises(ValueError):
            integration.format_phone_number("12345")
