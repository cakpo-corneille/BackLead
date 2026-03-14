from django.conf import settings
from django.test import TestCase, override_settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.utils import timezone
from datetime import timedelta
from rest_framework.test import APIClient
from .models import FormSchema, OwnerClient
from .services.portal.portal_services import ingest, recognize
from .services.portal.messages_services import send_verification_code, verify_code
from .services.dashboard.analytics import analytics_summary
from unittest.mock import patch, Mock
from core_data.utils.sms_backend import (
    ConsoleSMSBackend,
    FasterMessageBackend,
    Hub2SMSBackend,
    get_sms_backend
)
import uuid

User = get_user_model()


class FormSchemaModelTest(TestCase):
    """Tests du modèle FormSchema."""
    
    def setUp(self):
        self.user = User.objects.create_user(
            email='test@example.com',
            password='testpass123'
        )
    
    def test_form_schema_created_with_signal(self):
        """Le signal crée automatiquement un FormSchema."""
        schema = FormSchema.objects.filter(owner=self.user).first()
        self.assertIsNotNone(schema)
        self.assertTrue(schema.is_default)
        self.assertIsNotNone(schema.public_key)
    
    def test_public_key_is_unique(self):
        """Chaque schema a une public_key unique."""
        user2 = User.objects.create_user(email='test2@example.com', password='testpass123')
        schema1 = FormSchema.objects.get(owner=self.user)
        schema2 = FormSchema.objects.get(owner=user2)
        self.assertNotEqual(schema1.public_key, schema2.public_key)
    
    def test_rotate_public_key(self):
        """rotate_public_key génère une nouvelle clé."""
        schema = FormSchema.objects.get(owner=self.user)
        old_key = schema.public_key
        schema.rotate_public_key()
        schema.refresh_from_db()
        self.assertNotEqual(old_key, schema.public_key)
    
    def test_version_increments_on_save(self):
        """La version s'incrémente à chaque sauvegarde."""
        schema = FormSchema.objects.get(owner=self.user)
        old_version = schema.version
        schema.schema = {'fields': []}
        schema.save()
        self.assertEqual(schema.version, old_version + 1)


class OwnerClientModelTest(TestCase):
    """Tests du modèle OwnerClient."""
    
    def setUp(self):
        self.user = User.objects.create_user(email='test@example.com', password='testpass123')
    
    def test_create_lead(self):
        """Création d'un lead basique."""
        lead = OwnerClient.objects.create(
            owner=self.user,
            mac_address='AA:BB:CC:DD:EE:FF',
            payload={'nom': 'Test User'},
            email='user@test.com',
            client_token=str(uuid.uuid4())
        )
        self.assertEqual(lead.mac_address, 'AA:BB:CC:DD:EE:FF')
        self.assertEqual(lead.email, 'user@test.com')
        self.assertFalse(lead.is_verified)
        self.assertEqual(lead.recognition_level, 0)
    
    def test_unique_mac_per_owner(self):
        """Un owner ne peut avoir deux fois la même MAC."""
        OwnerClient.objects.create(
            owner=self.user,
            mac_address='AA:BB:CC:DD:EE:FF',
            payload={'nom': 'Test'},
            client_token=str(uuid.uuid4())
        )
        with self.assertRaises(Exception):
            OwnerClient.objects.create(
                owner=self.user,
                mac_address='AA:BB:CC:DD:EE:FF',
                payload={'nom': 'Test 2'},
                client_token=str(uuid.uuid4())
            )
    
    def test_unique_client_token_per_owner(self):
        """Un token ne peut pas être dupliqué pour un owner."""
        token = str(uuid.uuid4())
        OwnerClient.objects.create(
            owner=self.user,
            mac_address='AA:BB:CC:DD:EE:FF',
            payload={},
            client_token=token
        )
        with self.assertRaises(Exception):
            OwnerClient.objects.create(
                owner=self.user,
                mac_address='11:22:33:44:55:66',
                payload={},
                client_token=token
            )


class PortalAPITest(TestCase):
    """Tests des endpoints publics (/api/v1/portal/*)."""
    
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(email='test@example.com', password='testpass123')
        self.schema = FormSchema.objects.get(owner=self.user)
        
        self.schema.schema = {
            'fields': [
                {'name': 'nom', 'label': 'Nom', 'type': 'text', 'required': True},
                {'name': 'email', 'label': 'Email', 'type': 'email', 'required': True},
                {'name': 'phone', 'label': 'Téléphone', 'type': 'phone', 'required': False}
            ]
        }
        self.schema.save()
        self.public_key = str(self.schema.public_key)
    
    def test_provision_success(self):
        """Provision retourne le schéma et les infos owner."""
        response = self.client.get('/api/v1/portal/provision/', {'public_key': self.public_key})
        self.assertEqual(response.status_code, 200)
        self.assertIn('schema', response.data)
        self.assertIn('owner', response.data)
        self.assertIn('double_opt_enable', response.data)
        self.assertIn('preferred_channel', response.data)
    
    def test_provision_invalid_key(self):
        """Provision avec une clé invalide retourne 404."""
        fake_key = str(uuid.uuid4())
        response = self.client.get('/api/v1/portal/provision/', {'public_key': fake_key})
        self.assertEqual(response.status_code, 404)
    
    def test_provision_missing_key(self):
        """Provision sans public_key retourne 400."""
        response = self.client.get('/api/v1/portal/provision/')
        self.assertEqual(response.status_code, 400)
    
    def test_recognize_new_client(self):
        """Recognize d'un nouveau client retourne recognized=False."""
        response = self.client.post('/api/v1/portal/recognize/', {
            'public_key': self.public_key,
            'mac_address': 'AA:BB:CC:DD:EE:FF'
        }, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data['recognized'])
        self.assertFalse(response.data['is_verified'])
    
    def test_recognize_existing_client(self):
        """Recognize d'un client existant retourne recognized=True."""
        token = str(uuid.uuid4())
        OwnerClient.objects.create(
            owner=self.user,
            mac_address='AA:BB:CC:DD:EE:FF',
            payload={},
            client_token=token,
            is_verified=True
        )
        response = self.client.post('/api/v1/portal/recognize/', {
            'public_key': self.public_key,
            'mac_address': 'AA:BB:CC:DD:EE:FF'
        }, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data['recognized'])
        self.assertEqual(response.data['client_token'], token)
        self.assertTrue(response.data['is_verified'])
    
    def test_submit_new_lead_valid(self):
        """Soumettre un nouveau lead valide → 201."""
        self.schema.double_opt_enable = False
        self.schema.save()
        
        response = self.client.post('/api/v1/portal/submit/', {
            'public_key': self.public_key,
            'mac_address': 'AA:BB:CC:DD:EE:FF',
            'payload': {
                'nom': 'John Doe',
                'email': 'john.doe@example.com',
                'phone': '+2290197000000'
            }
        }, format='json')
        self.assertEqual(response.status_code, 201)
        self.assertTrue(response.data['created'])
        self.assertFalse(response.data['duplicate'])
        self.assertIn('client_token', response.data)
        
        lead = OwnerClient.objects.get(owner=self.user, mac_address='AA:BB:CC:DD:EE:FF')
        self.assertEqual(lead.payload['nom'], 'John Doe')
        self.assertEqual(lead.email, 'john.doe@example.com')
        self.assertEqual(lead.phone, '+2290197000000')
    
    def test_submit_invalid_email(self):
        """Email invalide → 400."""
        response = self.client.post('/api/v1/portal/submit/', {
            'public_key': self.public_key,
            'mac_address': 'AA:BB:CC:DD:EE:FF',
            'payload': {
                'nom': 'John',
                'email': 'invalid-email',
                'phone': '+22997000000'
            }
        }, format='json')
        self.assertEqual(response.status_code, 400)
    
    def test_submit_invalid_phone(self):
        """Téléphone invalide → 400."""
        response = self.client.post('/api/v1/portal/submit/', {
            'public_key': self.public_key,
            'mac_address': 'AA:BB:CC:DD:EE:FF',
            'payload': {
                'nom': 'John',
                'email': 'john@example.com',
                'phone': '12345'
            }
        }, format='json')
        self.assertEqual(response.status_code, 400)
    
    def test_submit_duplicate_mac(self):
        """Re-soumission même MAC → mise à jour."""
        self.schema.double_opt_enable = False
        self.schema.save()
        
        self.client.post('/api/v1/portal/submit/', {
            'public_key': self.public_key,
            'mac_address': 'AA:BB:CC:DD:EE:FF',
            'payload': {'nom': 'John', 'email': 'john@example.com', 'phone': '+2290197000000'}
        }, format='json')
        
        response = self.client.post('/api/v1/portal/submit/', {
            'public_key': self.public_key,
            'mac_address': 'AA:BB:CC:DD:EE:FF',
            'payload': {'nom': 'Jane', 'email': 'jane@example.com', 'phone': '+2290197111111'}
        }, format='json')

        self.assertEqual(response.status_code, 201)
        self.assertFalse(response.data['created'])
        self.assertTrue(response.data['duplicate'])
        
        lead = OwnerClient.objects.get(owner=self.user, mac_address='AA:BB:CC:DD:EE:FF')
        self.assertEqual(lead.payload['nom'], 'Jane')


class SMSBackendTest(TestCase):
    """Tests des backends SMS."""
    
    def test_console_backend_success(self):
        """ConsoleSMSBackend affiche dans la console."""
        backend = ConsoleSMSBackend()
        
        with patch('builtins.print') as mock_print:
            result = backend.send('+22997000000', 'Test message')
            
            self.assertTrue(result)
            mock_print.assert_called_once_with('[SMS] → +22997000000 : Test message')
    
    @override_settings(
        SMS_API_KEY='test_key',
        SMS_SENDER_ID='MyBusiness',
        SMS_API_URL='https://api.fastermessage.com/v1/send'
    )
    @patch('core_data.utils.sms_backend.requests.post')
    def test_fastermessage_backend_success(self, mock_post):
        """FasterMessageBackend envoie correctement."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {'status': 'success'}
        mock_post.return_value = mock_response
        
        backend = FasterMessageBackend()
        result = backend.send('+22997000000', 'Test code: 123456')
        
        self.assertTrue(result)
        mock_post.assert_called_once()
        
        call_args = mock_post.call_args
        payload = call_args.kwargs['json']
        self.assertEqual(payload['phone'], '22997000000')
        self.assertEqual(payload['apiKey'], 'test_key')
        self.assertEqual(payload['sender'], 'MyBusiness')
    
    @override_settings(
        SMS_API_KEY='test_key',
        SMS_SENDER_ID='MyBusiness'
    )
    @patch('core_data.utils.sms_backend.requests.post')
    def test_fastermessage_backend_failure(self, mock_post):
        """FasterMessageBackend gère les erreurs."""
        mock_response = Mock()
        mock_response.status_code = 400
        mock_response.json.return_value = {'status': 'error', 'message': 'Invalid phone'}
        mock_post.return_value = mock_response
        
        backend = FasterMessageBackend()
        result = backend.send('+22997000000', 'Test')
        
        self.assertFalse(result)
    
    @override_settings(
        SMS_API_TOKEN='test_token',
        SMS_SENDER_ID='MyBiz',
        SMS_API_URL='https://api.hub2.com/sms/send'
    )
    @patch('core_data.utils.sms_backend.requests.post')
    def test_hub2_backend_success(self, mock_post):
        """Hub2SMSBackend envoie correctement."""
        mock_response = Mock()
        mock_response.status_code = 201
        mock_post.return_value = mock_response
        
        backend = Hub2SMSBackend()
        result = backend.send('+22997000000', 'Test message')
        
        self.assertTrue(result)
        
        call_args = mock_post.call_args
        headers = call_args.kwargs['headers']
        self.assertEqual(headers['Authorization'], 'Bearer test_token')
        
        payload = call_args.kwargs['json']
        self.assertEqual(payload['to'], '+22997000000')
        self.assertEqual(payload['from'], 'MyBiz')
    
    @override_settings(SMS_PROVIDER='console')
    def test_get_sms_backend_console(self):
        """Factory retourne ConsoleSMSBackend."""
        with self.settings(SMS_PROVIDER='console'):
            backend = get_sms_backend()
            self.assertIsInstance(backend, ConsoleSMSBackend)
    
    @override_settings(SMS_PROVIDER='fastermessage')
    def test_get_sms_backend_fastermessage(self):
        """Factory retourne FasterMessageBackend."""
        
        with self.settings(SMS_PROVIDER='fastermessage'):
            backend = get_sms_backend()
            self.assertIsInstance(backend, FasterMessageBackend)

    @override_settings(SMS_PROVIDER='hub2')
    def test_get_sms_backend_hub2(self):
        """Factory retourne Hub2SMSBackend."""

        with self.settings(SMS_PROVIDER='hub2'):
            backend = get_sms_backend()
            self.assertIsInstance(backend, Hub2SMSBackend)
    
    @override_settings(SMS_PROVIDER='unknown')
    def test_get_sms_backend_fallback(self):
        """Factory retourne ConsoleSMSBackend par défaut."""
        with self.settings(SMS_PROVIDER='unknown'):
            backend = get_sms_backend()
            self.assertIsInstance(backend, ConsoleSMSBackend)


class DoubleOptInTest(TestCase):
    """Tests du double opt-in."""
    
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(email='test@example.com', password='testpass123')
        self.schema = FormSchema.objects.get(owner=self.user)
        self.schema.double_opt_enable = True
        self.schema.preferred_channel = 'email'
        self.schema.save()
        
        self.lead = OwnerClient.objects.create(
            owner=self.user,
            mac_address='AA:BB:CC:DD:EE:FF',
            payload={},
            email='user@test.com',
            client_token=str(uuid.uuid4()),
            is_verified=False
        )
    
    def tearDown(self):
        cache.clear()
    
    def test_send_verification_code(self):
        """Envoi d'un code de vérification."""
        success = send_verification_code(self.lead)
        self.assertTrue(success)
        
        cache_key = f"double_opt_{self.lead.client_token}"
        stored_code = cache.get(cache_key)
        self.assertIsNotNone(stored_code)
        self.assertEqual(len(stored_code), 6)
    
    def test_verify_code_success(self):
        """Vérification d'un code valide."""
        send_verification_code(self.lead)
        cache_key = f"double_opt_{self.lead.client_token}"
        code = cache.get(cache_key)
        
        success, error = verify_code(self.lead, code)
        self.assertTrue(success)
        self.assertEqual(error, "")
        
        self.assertIsNone(cache.get(cache_key))
    
    def test_verify_code_invalid(self):
        """Code invalide → échec."""
        send_verification_code(self.lead)
        success, error = verify_code(self.lead, "000000")
        self.assertFalse(success)
        self.assertIn("incorrect", error.lower())
    
    def test_verify_code_expired(self):
        """Code expiré → échec."""
        success, error = verify_code(self.lead, "123456")
        self.assertFalse(success)
        self.assertIn("expiré", error.lower())
    
    def test_confirm_endpoint(self):
        """Endpoint /confirm/ avec code valide."""
        send_verification_code(self.lead)
        cache_key = f"double_opt_{self.lead.client_token}"
        code = cache.get(cache_key)
        
        response = self.client.post('/api/v1/portal/confirm/', {
            'client_token': self.lead.client_token,
            'code': code
        }, format='json')
        
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data['ok'])
        
        self.lead.refresh_from_db()
        self.assertTrue(self.lead.is_verified)
    
    def test_resend_endpoint(self):
        """Endpoint /resend/ renvoie un nouveau code."""
        response = self.client.post('/api/v1/portal/resend/', {
            'client_token': self.lead.client_token
        }, format='json')
        
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data['ok'])


class DashboardAPITest(TestCase):
    """Tests des endpoints dashboard (/api/v1/schema/*)."""
    
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(email='test@example.com', password='testpass123')
        self.client.force_authenticate(user=self.user)
        self.schema = FormSchema.objects.get(owner=self.user)
    
    def test_get_schema_config(self):
        """GET /config/ retourne le schéma de l'owner."""
        response = self.client.get('/api/v1/schema/config/')
        self.assertEqual(response.status_code, 200)
        self.assertIn('schema', response.data)
        self.assertIn('public_key', response.data)
        self.assertIn('integration_snippet', response.data)
        self.assertIn('version', response.data)
    
    def test_update_schema_valid(self):
        """POST /update_schema/ avec schéma valide."""
        new_schema = {
            'fields': [
                {'name': 'nom', 'label': 'Nom', 'type': 'text', 'required': True},
                {'name': 'email', 'label': 'Email', 'type': 'email', 'required': True}
            ]
        }
        response = self.client.post('/api/v1/schema/update_schema/', {
            'schema': new_schema,
            'is_default': True
        }, format='json')
        
        self.assertEqual(response.status_code, 200)
        self.schema.refresh_from_db()
        self.assertEqual(self.schema.schema, new_schema)
    
    def test_update_schema_invalid_type(self):
        """Schéma avec type invalide → 400."""
        invalid_schema = {
            'fields': [
                {'name': 'nom', 'label': 'Nom', 'type': 'string', 'required': True}
            ]
        }
        response = self.client.post('/api/v1/schema/update_schema/', {
            'schema': invalid_schema
        }, format='json')
        
        self.assertEqual(response.status_code, 400)
    
    def test_update_schema_missing_email_or_phone(self):
        """Schéma sans email ni phone → 400."""
        invalid_schema = {
            'fields': [
                {'name': 'nom', 'label': 'Nom', 'type': 'text', 'required': True}
            ]
        }
        response = self.client.post('/api/v1/schema/update_schema/', {
            'schema': invalid_schema
        }, format='json')
        
        self.assertEqual(response.status_code, 400)
    
    def test_rotate_key(self):
        """POST /rotate_key/ génère une nouvelle clé."""
        old_key = str(self.schema.public_key)
        response = self.client.post('/api/v1/schema/rotate_key/')
        
        self.assertEqual(response.status_code, 200)
        self.assertIn('public_key', response.data)
        self.assertNotEqual(response.data['public_key'], old_key)
        
        self.schema.refresh_from_db()
        self.assertNotEqual(str(self.schema.public_key), old_key)
    
    def test_get_leads_list(self):
        """GET /analytics/leads/ retourne la liste paginée."""
        for i in range(5):
            OwnerClient.objects.create(
                owner=self.user,
                mac_address=f'AA:BB:CC:DD:EE:{i:02d}',
                payload={'nom': f'User {i}'},
                email=f'user{i}@test.com',
                client_token=str(uuid.uuid4())
            )
        
        response = self.client.get('/api/v1/analytics/leads/')
        self.assertEqual(response.status_code, 200)
        self.assertIn('results', response.data)
        self.assertEqual(len(response.data['results']), 5)


class AnalyticsSummaryTest(TestCase):
    """Tests du service analytics_summary et de l'endpoint /analytics/summary/."""
    
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(email='test@example.com', password='testpass123')
        self.client.force_authenticate(user=self.user)
        OwnerClient.objects.filter(owner=self.user).delete()
    
    def test_analytics_summary_empty(self):
        """Analytics sans leads retourne des stats vides."""
        data = analytics_summary(self.user.id)
        
        self.assertEqual(data['total_leads'], 0)
        self.assertEqual(data['leads_this_week'], 0)
        self.assertEqual(data['verified_leads'], 0)
        self.assertEqual(data['top_clients'], [])
        self.assertEqual(data['leads_by_hour'], [])
    
    def test_analytics_summary_with_leads(self):
        """Analytics avec leads retourne les bonnes stats."""
        for i in range(10):
            OwnerClient.objects.create(
                owner=self.user,
                mac_address=f'AA:BB:CC:DD:EE:{i:02d}',
                payload={'nom': f'User {i}'},
                email=f'user{i}@test.com',
                client_token=str(uuid.uuid4()),
                recognition_level=i * 5,
                is_verified=i % 2 == 0
            )
        
        data = analytics_summary(self.user.id)
        
        self.assertEqual(data['total_leads'], 10)
        self.assertEqual(data['verified_leads'], 5)
        self.assertIsInstance(data['top_clients'], list)
        self.assertIsInstance(data['leads_by_hour'], list)
    
    def test_top_clients_loyalty_threshold(self):
        """Seuls les clients au-dessus du seuil sont dans le top."""
        for i in range(1, 7):
            OwnerClient.objects.create(
                owner=self.user,
                mac_address=f'AA:BB:CC:DD:EE:{i:02d}',
                payload={'nom': f'User {i}'},
                email=f'user{i}@test.com',
                client_token=str(uuid.uuid4()),
                recognition_level=i * 10,
                is_verified=True
            )
        
        data = analytics_summary(self.user.id)
        
        top_clients = data['top_clients']
        
        for client in top_clients:
            self.assertGreaterEqual(client['recognition_level'], 40)
        
        self.assertEqual(len(top_clients), 3)
    
    def test_top_clients_data_structure(self):
        """Vérifier la structure des données du top clients."""
        OwnerClient.objects.create(
            owner=self.user,
            mac_address='AA:BB:CC:DD:EE:FF',
            payload={'nom': 'John Doe'},
            email='john@test.com',
            phone='+22997000000',
            client_token=str(uuid.uuid4()),
            recognition_level=50,
            is_verified=True
        )
        
        data = analytics_summary(self.user.id)
        top_clients = data['top_clients']
        
        self.assertEqual(len(top_clients), 1)
        
        client = top_clients[0]
        self.assertIn('id', client)
        self.assertIn('name', client)
        self.assertIn('email', client)
        self.assertIn('phone', client)
        self.assertIn('mac_address', client)
        self.assertIn('recognition_level', client)
        self.assertIn('loyalty_percentage', client)
        self.assertIn('last_seen', client)
        self.assertIn('created_at', client)
        self.assertIn('is_verified', client)
        
        self.assertEqual(client['name'], 'John Doe')
        self.assertEqual(client['email'], 'john@test.com')
        self.assertEqual(client['phone'], '+22997000000')
        self.assertEqual(client['mac_address'], 'AA:BB:CC:DD:EE:FF')
        self.assertEqual(client['recognition_level'], 50)
        self.assertEqual(client['loyalty_percentage'], 100.0)
        self.assertTrue(client['is_verified'])
    
    def test_top_clients_max_20(self):
        """Le top clients contient max 20 entrées."""
        for i in range(30):
            OwnerClient.objects.create(
                owner=self.user,
                mac_address=f'AA:BB:CC:DD:EE:{i:02d}',
                payload={'nom': f'User {i}'},
                email=f'user{i}@test.com',
                client_token=str(uuid.uuid4()),
                recognition_level=100,
                is_verified=True
            )
        
        data = analytics_summary(self.user.id)
        top_clients = data['top_clients']
        
        self.assertLessEqual(len(top_clients), 20)
    
    def test_leads_by_hour_last_24h(self):
        """leads_by_hour contient uniquement les dernières 24h."""
        from django.db.models import F
        
        OwnerClient.objects.all().delete()
        now = timezone.now()
        
        # Créer PUIS mettre à jour le timestamp (évite auto_now)
        old_lead = OwnerClient.objects.create(
            owner=self.user,
            mac_address='AA:BB:CC:DD:EE:01',
            payload={},
            email='old@test.com',
            client_token=str(uuid.uuid4())
        )
        OwnerClient.objects.filter(pk=old_lead.pk).update(created_at=now - timedelta(hours=25))
        
        recent_lead = OwnerClient.objects.create(
            owner=self.user,
            mac_address='AA:BB:CC:DD:EE:02',
            payload={},
            email='recent@test.com',
            client_token=str(uuid.uuid4())
        )
        OwnerClient.objects.filter(pk=recent_lead.pk).update(created_at=now - timedelta(hours=12))
        
        data = analytics_summary(self.user.id)
        leads_by_hour = data['leads_by_hour']
        
        total_in_24h = sum(entry['count'] for entry in leads_by_hour)
        self.assertEqual(total_in_24h, 1)
    
    def test_leads_by_hour_data_structure(self):
        """Vérifier la structure de leads_by_hour."""
        for i in range(3):
            OwnerClient.objects.create(
                owner=self.user,
                mac_address=f'AA:BB:CC:DD:EE:{i:02d}',
                payload={},
                email=f'user{i}@test.com',
                client_token=str(uuid.uuid4())
            )
        
        data = analytics_summary(self.user.id)
        leads_by_hour = data['leads_by_hour']
        
        if len(leads_by_hour) > 0:
            entry = leads_by_hour[0]
            self.assertIn('hour', entry)
            self.assertIn('count', entry)
            self.assertIsInstance(entry['count'], int)
    
    def test_analytics_summary_endpoint(self):
        """GET /analytics/summary/ retourne les bonnes données."""
        for i in range(5):
            OwnerClient.objects.create(
                owner=self.user,
                mac_address=f'AA:BB:CC:DD:EE:{i:02d}',
                payload={'nom': f'User {i}'},
                email=f'user{i}@test.com',
                client_token=str(uuid.uuid4()),
                recognition_level=i * 10,
                is_verified=True
            )
        
        response = self.client.get('/api/v1/analytics/summary/')
        
        self.assertEqual(response.status_code, 200)
        self.assertIn('total_leads', response.data)
        self.assertIn('leads_this_week', response.data)
        self.assertIn('verified_leads', response.data)
        self.assertIn('top_clients', response.data)
        self.assertIn('leads_by_hour', response.data)
        
        self.assertEqual(response.data['total_leads'], 5)
        self.assertEqual(response.data['verified_leads'], 5)

    def test_analytics_summary_return_rate(self):
        """Le taux de retour est calculé correctement."""
        for i in range(100):
            recognition_level = i % 10
            OwnerClient.objects.create(
                owner=self.user,
                mac_address=f'AA:BB:CC:DD:EE:{i:02d}',
                payload={'nom': f'User {i}'},
                email=f'user{i}@test.com',
                client_token=str(uuid.uuid4()),
                recognition_level=recognition_level,
                is_verified=True
            )
        
        data = analytics_summary(self.user.id)
        
        self.assertEqual(data['total_leads'], 100)
        
        expected_returning = 70
        expected_rate = 70.0
        
        self.assertEqual(data['return_rate'], expected_rate)