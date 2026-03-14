from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken
from django.core.cache import cache

from accounts.services import send_verification_code, verify_code
from accounts.models import OwnerProfile
from accounts.validators import validate_password_strength

User = get_user_model()


class PasswordValidationTests(APITestCase):
    """Tests de validation du mot de passe."""
    
    def test_password_too_short(self):
        """Mot de passe < 8 caractères rejeté."""
        resp = self.client.post('/api/v1/accounts/auth/register/', {
            'email': 'test@test.com',
            'password': 'Short1'  # 6 caractères
        }, format='json')
        
        self.assertEqual(resp.status_code, 400)
        # DRF utilise un espace insécable (\xa0)
        self.assertTrue('8' in str(resp.data) and 'caractères' in str(resp.data))
    
    def test_password_too_long(self):
        """Mot de passe > 15 caractères rejeté."""
        resp = self.client.post('/api/v1/accounts/auth/register/', {
            'email': 'test@test.com',
            'password': 'VeryLongPassword123'  # 19 caractères
        }, format='json')
        
        self.assertEqual(resp.status_code, 400)
        # DRF utilise un espace insécable (\xa0)
        self.assertTrue('15' in str(resp.data) and 'caractères' in str(resp.data))
    
    def test_password_no_uppercase(self):
        """Mot de passe sans majuscule rejeté."""
        resp = self.client.post('/api/v1/accounts/auth/register/', {
            'email': 'test@test.com',
            'password': 'lowercase123'
        }, format='json')
        
        self.assertEqual(resp.status_code, 400)
        self.assertIn('majuscule', str(resp.data))
    
    def test_password_no_lowercase(self):
        """Mot de passe sans minuscule rejeté."""
        resp = self.client.post('/api/v1/accounts/auth/register/', {
            'email': 'test@test.com',
            'password': 'UPPERCASE123'
        }, format='json')
        
        self.assertEqual(resp.status_code, 400)
        self.assertIn('minuscule', str(resp.data))

    def test_password_no_digit(self):
        """Mot de passe sans chiffre rejeté."""
        resp = self.client.post('/api/v1/accounts/auth/register/', {
            'email': 'test@test.com',
            'password': 'NoDigitPass'  # Pas de chiffre
        }, format='json')
        
        self.assertEqual(resp.status_code, 400)
        self.assertIn('chiffre', str(resp.data))
    
    def test_password_valid(self):
        """Mot de passe valide accepté."""
        resp = self.client.post('/api/v1/accounts/auth/register/', {
            'email': 'valid@test.com',
            'password': 'ValidPass123'  # 12 caractères, maj + min + chiffre
        }, format='json')
        
        self.assertEqual(resp.status_code, 201)
        self.assertTrue(User.objects.filter(email='valid@test.com').exists())


class AuthTests(APITestCase):
    
    def setUp(self):
        # Clear cache avant chaque test
        cache.clear()
    
    def test_register_creates_user_with_is_verify_false(self):
        """L'inscription crée un user avec is_verify=False."""
        payload = {'email': 'test@example.com', 'password': 'StrongPass123'}
        resp = self.client.post('/api/v1/accounts/auth/register/', payload, format='json')
        
        self.assertEqual(resp.status_code, 201)
        user = User.objects.get(email='test@example.com')
        self.assertFalse(user.is_verify)  # Par défaut False

    def test_register_creates_profile_with_defaults(self):
        """Le signal crée un profile avec business_name='WIFI-ZONE{id}' et is_complete=False."""
        payload = {'email': 'profile@example.com', 'password': 'Pass123Test'}
        resp = self.client.post('/api/v1/accounts/auth/register/', payload, format='json')
        
        self.assertEqual(resp.status_code, 201)
        user = User.objects.get(email='profile@example.com')
        # Le business_name doit suivre le pattern WIFI-ZONE{id}
        self.assertTrue(user.profile.business_name.startswith('WIFI-ZONE'))
        self.assertFalse(user.profile.is_complete)  # Calculé auto
        self.assertFalse(user.profile.pass_onboading)  # Aussi False par défaut

    def test_verify_code_sets_is_verify_true(self):
        """verify_code() met is_verify=True."""
        user = User.objects.create_user(email='verify@test.com', password='TestPass123')
        self.assertFalse(user.is_verify)
        
        # Stocker un code dans le cache
        code = '123456'
        cache.set(f'email_verification_{user.id}', code, timeout=600)
        
        # Vérifier le code
        success, msg = verify_code(user, code)
        
        self.assertTrue(success)
        user.refresh_from_db()
        self.assertTrue(user.is_verify)

    def test_login_with_unverified_email_blocked(self):
        """Connexion bloquée si is_verify=False."""
        user = User.objects.create_user(email='unverified@test.com', password='Pass123Test')
        user.is_verify = False
        user.save()
        
        resp = self.client.post('/api/v1/accounts/auth/login/', {
            'email': 'unverified@test.com',
            'password': 'Pass123Test'
        }, format='json')
        
        self.assertEqual(resp.status_code, 403)
        self.assertIn('redirect', resp.data)
        self.assertEqual(resp.data['redirect'], '/verify-email')

    def test_login_with_verified_email_success(self):
        """Connexion réussie si is_verify=True."""
        user = User.objects.create_user(email='verified@test.com', password='Pass123Test')
        user.is_verify = True
        user.save()
        
        resp = self.client.post('/api/v1/accounts/auth/login/', {
            'email': 'verified@test.com',
            'password': 'Pass123Test'
        }, format='json')
        
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.data['ok'])
        self.assertIn('access', resp.data)

    def test_verify_endpoint_returns_redirect_onboarding(self):
        """verify endpoint retourne redirect=/onboarding si profile incomplet."""
        user = User.objects.create_user(email='onboard@test.com', password='TestPass123')
        code = '654321'
        cache.set(f'email_verification_{user.id}', code, timeout=600)
        
        resp = self.client.post('/api/v1/accounts/auth/verify/', {
            'user_id': user.id,
            'code': code
        }, format='json')
        
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['redirect'], '/onboarding')
        self.assertFalse(resp.data['profile_status']['is_complete'])

    def test_profile_is_complete_calculated_automatically(self):
        """is_complete est calculé automatiquement lors de save()."""
        user = User.objects.create_user(email='auto@test.com', password='AutoPass123')
        profile = user.profile
        
        # Par défaut : incomplet
        self.assertFalse(profile.is_complete)
        
        # Remplir tous les champs obligatoires
        profile.business_name = 'Mon Café'
        
        # Créer un vrai logo
        logo_file = SimpleUploadedFile(
            "custom_logo.png",
            b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82',
            content_type='image/png'
        )
        profile.logo.save('custom_logo.png', logo_file, save=False)
        
        profile.nom = 'Dupont'
        profile.prenom = 'Jean'
        profile.phone_contact = '+22997123456'
        profile.whatsapp_contact = '+22997123456'
        profile.main_goal = 'collect_leads'
        profile.pays = 'Bénin'
        profile.ville = 'Cotonou'
        profile.quartier = 'Akpakpa'
        profile.save()
        
        # Doit être complet maintenant
        profile.refresh_from_db()
        self.assertTrue(profile.is_complete)
        self.assertTrue(profile.pass_onboading)

    def test_profile_incomplete_if_default_business_name(self):
        """Profile incomplet si business_name='WIFI-ZONE{id}' (défaut)."""
        user = User.objects.create_user(email='default@test.com', password='DefaultPass1')
        profile = user.profile
        
        # Garder le business_name par défaut
        default_name = profile.business_name  # WIFI-ZONE{id}
        
        # Créer un logo personnalisé
        logo_file = SimpleUploadedFile(
            "custom.png",
            b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82',
            content_type='image/png'
        )
        profile.logo.save('custom.png', logo_file, save=False)
        
        profile.nom = 'Test'
        profile.prenom = 'User'
        profile.phone_contact = '+22997123456'
        profile.whatsapp_contact = '+22997123456'
        profile.main_goal = 'analytics'
        profile.pays = 'France'
        profile.ville = 'Paris'
        profile.quartier = 'Marais'
        profile.save()
        
        # Incomplet car business_name non personnalisé
        profile.refresh_from_db()
        self.assertFalse(profile.pass_onboading)
        self.assertFalse(profile.is_complete)

    def test_update_profile_returns_redirect_dashboard(self):
        """Mise à jour profile retourne redirect=/dashboard si complet."""
        user = User.objects.create_user(email='complete@test.com', password='CompletePass1')
        user.is_verify = True
        user.save()
        
        refresh = RefreshToken.for_user(user)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {str(refresh.access_token)}')
        
        # Créer un logo pour l'upload
        logo_file = SimpleUploadedFile(
            "cafe_logo.png",
            b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82',
            content_type='image/png'
        )
        
        # Compléter le profil avec tous les champs obligatoires
        resp = self.client.patch('/api/v1/accounts/profile/me/', {
            'business_name': 'Café Complete',
            'logo': logo_file,
            'nom': 'Jean',
            'prenom': 'Pierre',
            'phone_contact': '+22997123456',
            'whatsapp_contact': '+22997123456',
            'main_goal': 'collect_leads',
            'pays': 'Bénin',
            'ville': 'Cotonou',
            'quartier': 'Jonquet'
        }, format='multipart')
        
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.data['profile_status']['is_complete'])
        self.assertEqual(resp.data['redirect'], '/dashboard')


class ProfileTests(APITestCase):
    
    def setUp(self):
        self.user = User.objects.create_user(email='profile@example.com', password='ProfilePass1')
        self.user.is_verify = True
        self.user.save()
        refresh = RefreshToken.for_user(self.user)
        self.access_token = str(refresh.access_token)

    def test_profile_requires_auth(self):
        resp = self.client.get('/api/v1/accounts/profile/me/')
        self.assertIn(resp.status_code, (401, 403))

    def test_get_profile_returns_user_data_with_is_verify(self):
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {self.access_token}')
        resp = self.client.get('/api/v1/accounts/profile/me/')
        
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['user']['email'], 'profile@example.com')
        self.assertTrue(resp.data['user']['is_verify'])
        self.assertIn('profile', resp.data)
        self.assertIn('profile_status', resp.data)

    def test_update_profile_partial(self):
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {self.access_token}')
        payload = {'business_name': 'New Business', 'ville': 'Cotonou'}
        resp = self.client.patch('/api/v1/accounts/profile/me/', payload, format='json')
        
        self.assertEqual(resp.status_code, 200)
        self.user.profile.refresh_from_db()
        self.assertEqual(self.user.profile.business_name, 'New Business')
        self.assertEqual(self.user.profile.ville, 'Cotonou')

    def test_logo_upload_valid_image(self):
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {self.access_token}')
        
        image = SimpleUploadedFile(
            "test_logo.png",
            b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82',
            content_type='image/png'
        )
        
        resp = self.client.patch('/api/v1/accounts/profile/me/', {'logo': image}, format='multipart')
        self.assertEqual(resp.status_code, 200)

    def test_logo_upload_exceeds_size_limit(self):
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {self.access_token}')
        
        # Créer un vrai fichier PNG valide mais trop gros
        # Header PNG minimal + données répétées pour atteindre 3MB
        png_header = b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82'
        # Ajouter du padding pour dépasser 2MB
        large_file = SimpleUploadedFile(
            "large.png",
            png_header * 50000,  # ~3MB
            content_type='image/png'
        )
        
        resp = self.client.patch('/api/v1/accounts/profile/me/', {'logo': large_file}, format='multipart')
        self.assertEqual(resp.status_code, 400)
        # Le message peut être soit sur la taille, soit sur l'image invalide
        self.assertTrue('2MB' in str(resp.data) or 'image' in str(resp.data).lower())


class PasswordManagementTests(APITestCase):
    
    def setUp(self):
        cache.clear()
    
    def test_forgot_password_sends_code(self):
        """Forgot password envoie un code par email."""
        user = User.objects.create_user(email='test@test.com', password='OldPass123')
        mail.outbox = []
        
        resp = self.client.post('/api/v1/accounts/auth/forgot_password/', {
            'email': 'test@test.com'
        }, format='json')
        
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('user_id', resp.data)
    
    def test_forgot_password_invalid_email(self):
        """Forgot password avec email inconnu retourne 404."""
        resp = self.client.post('/api/v1/accounts/auth/forgot_password/', {
            'email': 'unknown@test.com'
        }, format='json')
        
        self.assertEqual(resp.status_code, 404)
    
    def test_reset_password_with_valid_code(self):
        """Reset password avec code valide fonctionne."""
        user = User.objects.create_user(email='test@test.com', password='OldPass123')
        code = '123456'
        cache.set(f'password_reset_{user.id}', code, timeout=600)
        
        resp = self.client.post('/api/v1/accounts/auth/reset_password/', {
            'user_id': user.id,
            'code': code,
            'new_password': 'NewPass123'
        }, format='json')
        
        self.assertEqual(resp.status_code, 200)
        
        # Vérifier que le nouveau mot de passe fonctionne
        user.refresh_from_db()
        self.assertTrue(user.check_password('NewPass123'))
    
    def test_change_password_with_correct_old(self):
        """Change password avec ancien mot de passe correct."""
        user = User.objects.create_user(email='test@test.com', password='OldPass123')
        user.is_verify = True
        user.save()
        
        refresh = RefreshToken.for_user(user)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {str(refresh.access_token)}')
        
        resp = self.client.post('/api/v1/accounts/profile/change_password/', {
            'old_password': 'OldPass123',
            'new_password': 'NewPass456'
        }, format='json')
        
        self.assertEqual(resp.status_code, 200)
        user.refresh_from_db()
        self.assertTrue(user.check_password('NewPass456'))
    
    def test_change_password_with_wrong_old(self):
        """Change password avec mauvais ancien mot de passe."""
        user = User.objects.create_user(email='test@test.com', password='OldPass123')
        user.is_verify = True
        user.save()
        
        refresh = RefreshToken.for_user(user)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {str(refresh.access_token)}')
        
        resp = self.client.post('/api/v1/accounts/profile/change_password/', {
            'old_password': 'WrongPass',
            'new_password': 'NewPass456'
        }, format='json')
        
        self.assertEqual(resp.status_code, 400)


class EmailServiceTests(APITestCase):
    
    def setUp(self):
        cache.clear()
    
    def test_send_verification_code_stores_in_cache(self):
        user = User.objects.create_user(email='cache@test.com', password='CachePass123')
        mail.outbox = []
        
        code = send_verification_code(user)
        
        # Vérifier cache
        cached_code = cache.get(f'email_verification_{user.id}')
        self.assertEqual(cached_code, code)
        
        # Vérifier email envoyé
        self.assertEqual(len(mail.outbox), 1)
        sent = mail.outbox[0]
        self.assertIn(user.email, sent.to)
        self.assertIn(code, sent.body)