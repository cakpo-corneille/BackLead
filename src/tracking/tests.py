"""
Tests pour l'app tracking — v2 (scripts MikroTik on-login / on-logout).

Couvre :
- Parsers MikroTik (parse_mikrotik_uptime)
- Modèles : TicketPlan, ConnectionSession
- Services : match_ticket_plan
- hotspot_service : validate_owner_key, handle_login, handle_logout,
                    close_expired_sessions
- Celery : close_expired_sessions task
- Endpoints publics : POST /api/v1/sessions/login/, POST /api/v1/sessions/logout/
- Endpoints dashboard : /api/v1/plans/, /api/v1/sessions/, /api/v1/tracking-analytics/
"""
import uuid
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from core_data.models import FormSchema, OwnerClient
from tracking.models import (
    TicketPlan,
    ConnectionSession,
    parse_mikrotik_uptime,
)
from tracking.services import match_ticket_plan
from tracking.hotspot_service import (
    validate_owner_key,
    handle_login,
    handle_logout,
    close_expired_sessions,
)
from tracking.tasks import close_expired_sessions as close_expired_task


User = get_user_model()


# ============================================================
# Helpers
# ============================================================

def make_owner(email='owner@example.com', password='Pass1234!'):
    return User.objects.create_user(email=email, password=password, is_verify=True)


def make_client(owner, mac='AA:BB:CC:DD:EE:FF', email='lead@example.com', phone=None):
    return OwnerClient.objects.create(
        owner=owner,
        mac_address=mac,
        payload={'email': email, 'phone': phone},
        email=email,
        phone=phone,
    )


def get_public_key(owner):
    return FormSchema.objects.get(owner=owner).public_key


def auth_headers(user):
    """Retourne un client APITestCase authentifié via JWT."""
    refresh = RefreshToken.for_user(user)
    return str(refresh.access_token)


# ============================================================
# 1. PARSERS MikroTik
# ============================================================

class ParseMikrotikUptimeTest(TestCase):

    def test_full_format(self):
        self.assertEqual(parse_mikrotik_uptime('1d2h34m56s'),
                         86400 + 7200 + 34 * 60 + 56)

    def test_minutes_seconds_only(self):
        self.assertEqual(parse_mikrotik_uptime('5m12s'), 5 * 60 + 12)

    def test_hours_seconds_only(self):
        self.assertEqual(parse_mikrotik_uptime('2h3s'), 2 * 3600 + 3)

    def test_seconds_only(self):
        self.assertEqual(parse_mikrotik_uptime('45s'), 45)

    def test_hours_only(self):
        self.assertEqual(parse_mikrotik_uptime('4h'), 4 * 3600)

    def test_empty_string(self):
        self.assertEqual(parse_mikrotik_uptime(''), 0)

    def test_none(self):
        self.assertEqual(parse_mikrotik_uptime(None), 0)

    def test_common_plans(self):
        self.assertEqual(parse_mikrotik_uptime('1h'),  3600)
        self.assertEqual(parse_mikrotik_uptime('4h'),  14400)
        self.assertEqual(parse_mikrotik_uptime('12h'), 43200)
        self.assertEqual(parse_mikrotik_uptime('24h'), 86400)


# ============================================================
# 2. MODÈLES
# ============================================================

class TicketPlanModelTest(TestCase):

    def setUp(self):
        self.owner = make_owner()

    def test_str(self):
        plan = TicketPlan.objects.create(
            owner=self.owner, name='Pass 4h', price_fcfa=200, duration_minutes=240,
        )
        self.assertIn('Pass 4h', str(plan))
        self.assertIn('240', str(plan))
        self.assertIn('200', str(plan))

    def test_default_is_active(self):
        plan = TicketPlan.objects.create(
            owner=self.owner, name='X', price_fcfa=100, duration_minutes=60,
        )
        self.assertTrue(plan.is_active)

    def test_ordering_by_price(self):
        TicketPlan.objects.create(owner=self.owner, name='Cher', price_fcfa=500, duration_minutes=240)
        TicketPlan.objects.create(owner=self.owner, name='Pas cher', price_fcfa=100, duration_minutes=60)
        plans = list(TicketPlan.objects.filter(owner=self.owner))
        self.assertEqual(plans[0].name, 'Pas cher')


class ConnectionSessionModelTest(TestCase):

    def setUp(self):
        self.owner      = make_owner()
        self.client_obj = make_client(self.owner)

    def _session(self, **kwargs):
        return ConnectionSession.objects.create(
            owner=self.owner, client=self.client_obj,
            mac_address='AA:BB:CC:DD:EE:FF', **kwargs,
        )

    def test_duration_seconds_from_ended_at(self):
        s = self._session()
        ConnectionSession.objects.filter(pk=s.pk).update(
            started_at=timezone.now() - timedelta(seconds=300),
            ended_at=timezone.now(),
        )
        s.refresh_from_db()
        self.assertAlmostEqual(s.duration_seconds, 300, delta=2)

    def test_duration_seconds_fallback_to_uptime(self):
        s = self._session(uptime_seconds=180)
        self.assertEqual(s.duration_seconds, 180)

    def test_duration_human(self):
        s = self._session(uptime_seconds=3661)
        self.assertIn('1h', s.duration_human)
        self.assertIn('1m', s.duration_human)
        self.assertIn('1s', s.duration_human)

    def test_total_mb(self):
        s = self._session(bytes_downloaded=1024 * 1024, bytes_uploaded=512 * 1024)
        self.assertAlmostEqual(s.total_mb, 1.5, places=1)

    def test_default_is_active(self):
        s = self._session()
        self.assertTrue(s.is_active)

    def test_session_key_is_uuid(self):
        s = self._session()
        self.assertIsInstance(s.session_key, uuid.UUID)

    def test_disconnect_cause_default_empty(self):
        s = self._session()
        self.assertEqual(s.disconnect_cause, '')


# ============================================================
# 3. SERVICE — match_ticket_plan
# ============================================================

class MatchTicketPlanTest(TestCase):

    def setUp(self):
        self.owner = make_owner()

    def test_exact_match_1h(self):
        plan = TicketPlan.objects.create(
            owner=self.owner, name='Pass 1h', price_fcfa=100, duration_minutes=60,
        )
        self.assertEqual(match_ticket_plan(self.owner, 3600), plan)

    def test_exact_match_4h(self):
        plan = TicketPlan.objects.create(
            owner=self.owner, name='Pass 4h', price_fcfa=200, duration_minutes=240,
        )
        self.assertEqual(match_ticket_plan(self.owner, 14400), plan)

    def test_no_match_on_approximate_timeout(self):
        # Le matching est désormais exact : 3500s ne correspond à aucun plan
        # (1h = 3600s, 4h = 14400s) → doit retourner None.
        TicketPlan.objects.create(
            owner=self.owner, name='Pass 1h', price_fcfa=100, duration_minutes=60,
        )
        TicketPlan.objects.create(
            owner=self.owner, name='Pass 4h', price_fcfa=200, duration_minutes=240,
        )
        self.assertIsNone(match_ticket_plan(self.owner, 3500))

    def test_returns_none_when_no_plans(self):
        self.assertIsNone(match_ticket_plan(self.owner, 3600))

    def test_returns_none_for_zero_timeout(self):
        TicketPlan.objects.create(
            owner=self.owner, name='Pass 1h', price_fcfa=100, duration_minutes=60,
        )
        self.assertIsNone(match_ticket_plan(self.owner, 0))

    def test_ignores_inactive_plans(self):
        TicketPlan.objects.create(
            owner=self.owner, name='Inactif', price_fcfa=100,
            duration_minutes=60, is_active=False,
        )
        self.assertIsNone(match_ticket_plan(self.owner, 3600))

    def test_isolates_by_owner(self):
        other = make_owner('other@x.com')
        TicketPlan.objects.create(
            owner=other, name='Pas le mien', price_fcfa=100, duration_minutes=60,
        )
        self.assertIsNone(match_ticket_plan(self.owner, 3600))


# ============================================================
# 4. HOTSPOT SERVICE — validate_owner_key
# ============================================================

class ValidateOwnerKeyTest(TestCase):

    def setUp(self):
        self.owner      = make_owner('hotspot_key@x.com')
        self.public_key = str(get_public_key(self.owner))

    def test_valid_key_returns_owner(self):
        self.assertEqual(validate_owner_key(self.public_key), self.owner)

    def test_invalid_key_raises(self):
        with self.assertRaises(ValueError):
            validate_owner_key(str(uuid.uuid4()))


# ============================================================
# 5. HOTSPOT SERVICE — handle_login
# ============================================================

class HandleLoginTest(TestCase):

    def setUp(self):
        self.owner      = make_owner('login_test@x.com')
        self.public_key = str(get_public_key(self.owner))
        self.plan_1h    = TicketPlan.objects.create(
            owner=self.owner, name='Pass 1h', price_fcfa=200, duration_minutes=60,
        )
        self.plan_4h    = TicketPlan.objects.create(
            owner=self.owner, name='Pass 4h', price_fcfa=500, duration_minutes=240,
        )
        # Client connu par défaut — doit exister avant tout appel handle_login
        self.client_obj = make_client(self.owner, mac='DC:A6:32:AA:BB:CC')

    def _data(self, mac='DC:A6:32:AA:BB:CC', uptime_limit='1h', session_id='*1A2B'):
        return {
            'mac':          mac,
            'ip':           '192.168.88.105',
            'user':         'ticket_abc123',
            'session_id':   session_id,
            'uptime_limit': uptime_limit,
            'owner_key':    self.public_key,
        }

    def test_creates_session_for_known_client(self):
        # self.client_obj est déjà créé dans setUp avec ce MAC
        session = handle_login(self.owner, self._data())
        self.assertIsNotNone(session.pk)
        self.assertTrue(session.is_active)
        self.assertEqual(session.mac_address, 'DC:A6:32:AA:BB:CC')

    def test_ignores_login_for_unknown_mac(self):
        # Un client inconnu (MAC jamais vu) ne doit pas créer de session.
        # handle_login retourne None et n'insère rien en base.
        mac = 'FF:EE:DD:CC:BB:AA'
        session = handle_login(self.owner, self._data(mac=mac))
        self.assertIsNone(session)
        self.assertFalse(OwnerClient.objects.filter(owner=self.owner, mac_address=mac).exists())
        self.assertFalse(ConnectionSession.objects.filter(mac_address=mac).exists())

    def test_matches_1h_plan(self):
        session = handle_login(self.owner, self._data(uptime_limit='1h'))
        self.assertEqual(session.ticket_plan, self.plan_1h)

    def test_matches_4h_plan(self):
        session = handle_login(self.owner, self._data(uptime_limit='4h'))
        self.assertEqual(session.ticket_plan, self.plan_4h)

    def test_no_plan_match_when_no_plans(self):
        TicketPlan.objects.filter(owner=self.owner).delete()
        # Le client existe (créé dans setUp) — seul le plan est absent
        session = handle_login(self.owner, self._data(uptime_limit='1h'))
        self.assertIsNotNone(session)
        self.assertIsNone(session.ticket_plan)

    def test_stores_mikrotik_session_id(self):
        session = handle_login(self.owner, self._data(session_id='*DEADBEEF'))
        self.assertEqual(session.mikrotik_session_id, '*DEADBEEF')

    def test_stores_session_timeout_seconds(self):
        session = handle_login(self.owner, self._data(uptime_limit='1h'))
        self.assertEqual(session.session_timeout_seconds, 3600)

    def test_normalizes_mac_dashes(self):
        session = handle_login(self.owner, self._data(mac='DC-A6-32-AA-BB-CC'))
        self.assertEqual(session.mac_address, 'DC:A6:32:AA:BB:CC')


# ============================================================
# 6. HOTSPOT SERVICE — handle_logout
# ============================================================

class HandleLogoutTest(TestCase):

    def setUp(self):
        self.owner      = make_owner('logout_test@x.com')
        self.public_key = str(get_public_key(self.owner))
        self.client_obj = make_client(self.owner)
        self.session    = ConnectionSession.objects.create(
            owner=self.owner,
            client=self.client_obj,
            mac_address='AA:BB:CC:DD:EE:FF',
            mikrotik_session_id='*SESSION1',
            session_timeout_seconds=3600,
            is_active=True,
        )

    def _data(self, cause='session-timeout', session_id='*SESSION1'):
        return {
            'mac':        'AA:BB:CC:DD:EE:FF',
            'session_id': session_id,
            'uptime':     '47m23s',
            'bytes_in':   '45234567',
            'bytes_out':  '1234567',
            'cause':      cause,
            'owner_key':  self.public_key,
        }

    def test_closes_session(self):
        handle_logout(self.owner, self._data())
        self.session.refresh_from_db()
        self.assertFalse(self.session.is_active)
        self.assertIsNotNone(self.session.ended_at)

    def test_stores_uptime(self):
        handle_logout(self.owner, self._data())
        self.session.refresh_from_db()
        self.assertEqual(self.session.uptime_seconds, 47 * 60 + 23)

    def test_stores_bytes(self):
        handle_logout(self.owner, self._data())
        self.session.refresh_from_db()
        self.assertEqual(self.session.bytes_downloaded, 45234567)
        self.assertEqual(self.session.bytes_uploaded, 1234567)

    def test_stores_cause(self):
        handle_logout(self.owner, self._data(cause='user-request'))
        self.session.refresh_from_db()
        self.assertEqual(self.session.disconnect_cause, 'user-request')

    def test_returns_none_for_unknown_session_id(self):
        result = handle_logout(self.owner, self._data(session_id='*UNKNOWN'))
        self.assertIsNone(result)

    def test_idempotent_on_already_closed_session(self):
        self.session.is_active = False
        self.session.save()
        result = handle_logout(self.owner, self._data())
        self.assertIsNotNone(result)

    def test_each_cause_value_stored_correctly(self):
        causes = ['session-timeout', 'lost-service', 'user-request', 'admin-reset']
        for i, cause in enumerate(causes):
            s = ConnectionSession.objects.create(
                owner=self.owner, client=self.client_obj,
                mac_address='AA:BB:CC:DD:EE:FF',
                mikrotik_session_id=f'*CAUSE{i}',
                is_active=True,
            )
            handle_logout(self.owner, self._data(cause=cause, session_id=f'*CAUSE{i}'))
            s.refresh_from_db()
            self.assertEqual(s.disconnect_cause, cause)


# ============================================================
# 7. HOTSPOT SERVICE — close_expired_sessions
# ============================================================

class CloseExpiredSessionsTest(TestCase):

    def setUp(self):
        self.owner      = make_owner('expired@x.com')
        self.client_obj = make_client(self.owner)

    def _session(self, started_ago_seconds, timeout_seconds, is_active=True):
        s = ConnectionSession.objects.create(
            owner=self.owner,
            client=self.client_obj,
            mac_address='AA:BB:CC:DD:EE:FF',
            session_timeout_seconds=timeout_seconds,
            is_active=is_active,
        )
        ConnectionSession.objects.filter(pk=s.pk).update(
            started_at=timezone.now() - timedelta(seconds=started_ago_seconds)
        )
        s.refresh_from_db()
        return s

    def test_closes_expired_session(self):
        s = self._session(started_ago_seconds=7200, timeout_seconds=3600)
        count = close_expired_sessions()
        self.assertEqual(count, 1)
        s.refresh_from_db()
        self.assertFalse(s.is_active)
        self.assertEqual(s.disconnect_cause, 'expired-by-server')

    def test_does_not_close_non_expired_session(self):
        s = self._session(started_ago_seconds=1800, timeout_seconds=3600)
        count = close_expired_sessions()
        self.assertEqual(count, 0)
        s.refresh_from_db()
        self.assertTrue(s.is_active)

    def test_ignores_already_closed_session(self):
        self._session(started_ago_seconds=7200, timeout_seconds=3600, is_active=False)
        count = close_expired_sessions()
        self.assertEqual(count, 0)

    def test_ignores_session_without_timeout(self):
        s = self._session(started_ago_seconds=7200, timeout_seconds=0)
        count = close_expired_sessions()
        self.assertEqual(count, 0)
        s.refresh_from_db()
        self.assertTrue(s.is_active)


# ============================================================
# 8. CELERY TASK
# ============================================================

@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
class CeleryTaskTest(TestCase):

    def setUp(self):
        self.owner      = make_owner('celery@x.com')
        self.client_obj = make_client(self.owner)

    def test_task_closes_expired_sessions(self):
        s = ConnectionSession.objects.create(
            owner=self.owner, client=self.client_obj,
            mac_address='AA:BB:CC:DD:EE:FF',
            session_timeout_seconds=3600, is_active=True,
        )
        ConnectionSession.objects.filter(pk=s.pk).update(
            started_at=timezone.now() - timedelta(seconds=7200)
        )
        close_expired_task.apply()
        s.refresh_from_db()
        self.assertFalse(s.is_active)

    def test_task_leaves_active_sessions_untouched(self):
        s = ConnectionSession.objects.create(
            owner=self.owner, client=self.client_obj,
            mac_address='AA:BB:CC:DD:EE:FF',
            session_timeout_seconds=3600, is_active=True,
        )
        ConnectionSession.objects.filter(pk=s.pk).update(
            started_at=timezone.now() - timedelta(minutes=10)
        )
        close_expired_task.apply()
        s.refresh_from_db()
        self.assertTrue(s.is_active)


# ============================================================
# 9. ENDPOINTS HOTSPOT — POST /api/v1/sessions/login/ & /logout/
# Les endpoints hotspot utilisent owner_key (AllowAny) mais le JWT
# global peut interférer. On bypasse avec HTTP_AUTHORIZATION vide
# et on vérifie que le système répond sur la owner_key seule.
# ============================================================

class HotspotEndpointsTest(APITestCase):
    """
    Tests des endpoints publics MikroTik (on-login / on-logout).
    Ces endpoints n'utilisent pas JWT — authentification via owner_key uniquement.
    On utilise un APIClient vierge (sans force_authenticate) pour simuler
    exactement ce que fait un routeur MikroTik : une requête HTTP brute sans token.
    """

    LOGIN_URL  = '/api/v1/sessions/login/'
    LOGOUT_URL = '/api/v1/sessions/logout/'

    def setUp(self):
        from rest_framework.test import APIClient
        self.owner      = make_owner('hotspot_ep@x.com')
        self.public_key = str(get_public_key(self.owner))
        self.plan_1h    = TicketPlan.objects.create(
            owner=self.owner, name='Pass 1h', price_fcfa=200, duration_minutes=60,
        )
        # Client connu — doit exister avant les appels login
        self.known_client = make_client(self.owner, mac='DC:A6:32:AA:BB:CC')
        # Client vierge — aucune auth configurée, simule le routeur MikroTik
        self.router_client = APIClient()

    def _login_data(self, mac='DC:A6:32:AA:BB:CC', owner_key=None):
        return {
            'mac':          mac,
            'ip':           '192.168.88.10',
            'user':         'ticket_xyz',
            'session_id':   '*ABCD1234',
            'uptime_limit': '1h',
            'owner_key':    owner_key or self.public_key,
        }

    def _logout_data(self, session_id='*ABCD1234', owner_key=None):
        return {
            'mac':        'DC:A6:32:AA:BB:CC',
            'session_id': session_id,
            'uptime':     '55m10s',
            'bytes_in':   '12345678',
            'bytes_out':  '987654',
            'cause':      'session-timeout',
            'owner_key':  owner_key or self.public_key,
        }

    def test_login_creates_session(self):
        r = self.router_client.post(self.LOGIN_URL, self._login_data(), format='json')
        self.assertEqual(r.status_code, 201)
        self.assertTrue(r.data['ok'])
        self.assertIn('session_id', r.data)
        self.assertTrue(ConnectionSession.objects.filter(mikrotik_session_id='*ABCD1234').exists())

    def test_login_unknown_client_returns_ok_false(self):
        # Un MAC inconnu (client n'ayant pas rempli le portail) ne crée pas de session.
        data = self._login_data(mac='00:11:22:33:44:55')
        r = self.router_client.post(self.LOGIN_URL, data, format='json')
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.data['ok'])
        self.assertFalse(ConnectionSession.objects.filter(mac_address='00:11:22:33:44:55').exists())

    def test_login_invalid_owner_key(self):
        data = self._login_data(owner_key=str(uuid.uuid4()))
        r = self.router_client.post(self.LOGIN_URL, data, format='json')
        self.assertEqual(r.status_code, 401)

    def test_login_missing_field(self):
        data = self._login_data()
        del data['session_id']
        r = self.router_client.post(self.LOGIN_URL, data, format='json')
        self.assertEqual(r.status_code, 400)

    def test_login_normalizes_mac_with_dashes(self):
        data = self._login_data(mac='DC-A6-32-AA-BB-CC')
        r = self.router_client.post(self.LOGIN_URL, data, format='json')
        self.assertEqual(r.status_code, 201)
        s = ConnectionSession.objects.get(mikrotik_session_id='*ABCD1234')
        self.assertEqual(s.mac_address, 'DC:A6:32:AA:BB:CC')

    def test_login_no_auth_required(self):
        # Vérifie qu'un routeur sans JWT peut appeler l'endpoint
        r = self.router_client.post(self.LOGIN_URL, self._login_data(), format='json')
        self.assertEqual(r.status_code, 201)

    def test_logout_closes_session(self):
        self.router_client.post(self.LOGIN_URL, self._login_data(), format='json')
        r = self.router_client.post(self.LOGOUT_URL, self._logout_data(), format='json')
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.data['ok'])
        s = ConnectionSession.objects.get(mikrotik_session_id='*ABCD1234')
        self.assertFalse(s.is_active)
        self.assertEqual(s.disconnect_cause, 'session-timeout')

    def test_logout_invalid_owner_key(self):
        data = self._logout_data(owner_key=str(uuid.uuid4()))
        r = self.router_client.post(self.LOGOUT_URL, data, format='json')
        self.assertEqual(r.status_code, 401)

    def test_logout_unknown_session_id_returns_200(self):
        r = self.router_client.post(self.LOGOUT_URL, self._logout_data(session_id='*UNKNOWN'), format='json')
        self.assertEqual(r.status_code, 200)


# ============================================================
# 10. ENDPOINTS DASHBOARD — /api/v1/plans/
# ============================================================

class TicketPlanAPITest(APITestCase):
    # Le router enregistre r'plans' → URL = /api/v1/plans/
    URL = '/api/v1/plans/'

    def setUp(self):
        self.owner = make_owner('owner1@example.com')
        self.other = make_owner('owner2@example.com')
        self.client.force_authenticate(self.owner)

    def test_list_only_own_plans(self):
        TicketPlan.objects.create(owner=self.owner, name='Mine',   price_fcfa=100, duration_minutes=60)
        TicketPlan.objects.create(owner=self.other, name='Theirs', price_fcfa=100, duration_minutes=60)
        r = self.client.get(self.URL)
        self.assertEqual(r.status_code, 200)
        names = [p['name'] for p in r.data]
        self.assertIn('Mine', names)
        self.assertNotIn('Theirs', names)

    def test_create_assigns_owner(self):
        r = self.client.post(self.URL, {
            'name': 'Pass 4h', 'price_fcfa': 200, 'duration_minutes': 240,
        }, format='json')
        self.assertEqual(r.status_code, 201)
        self.assertEqual(TicketPlan.objects.get(name='Pass 4h').owner, self.owner)

    def test_response_has_no_obsolete_limit_fields(self):
        r = self.client.post(self.URL, {
            'name': 'Pass 1h', 'price_fcfa': 100, 'duration_minutes': 60,
        }, format='json')
        self.assertEqual(r.status_code, 201)
        self.assertNotIn('download_limit_mb', r.data)
        self.assertNotIn('upload_limit_mb', r.data)

    def test_validate_negative_price(self):
        r = self.client.post(self.URL, {
            'name': 'X', 'price_fcfa': -1, 'duration_minutes': 60,
        }, format='json')
        self.assertEqual(r.status_code, 400)

    def test_validate_zero_duration(self):
        r = self.client.post(self.URL, {
            'name': 'X', 'price_fcfa': 100, 'duration_minutes': 0,
        }, format='json')
        self.assertEqual(r.status_code, 400)

    def test_update_own_plan(self):
        plan = TicketPlan.objects.create(owner=self.owner, name='Old', price_fcfa=100, duration_minutes=60)
        r = self.client.patch(f'{self.URL}{plan.id}/', {'name': 'New'}, format='json')
        self.assertEqual(r.status_code, 200)
        plan.refresh_from_db()
        self.assertEqual(plan.name, 'New')

    def test_cannot_access_others_plan(self):
        plan = TicketPlan.objects.create(owner=self.other, name='Theirs', price_fcfa=100, duration_minutes=60)
        r = self.client.get(f'{self.URL}{plan.id}/')
        self.assertEqual(r.status_code, 404)

    def test_delete_own_plan(self):
        plan = TicketPlan.objects.create(owner=self.owner, name='X', price_fcfa=100, duration_minutes=60)
        r = self.client.delete(f'{self.URL}{plan.id}/')
        self.assertEqual(r.status_code, 204)
        self.assertFalse(TicketPlan.objects.filter(pk=plan.pk).exists())

    def test_unauthenticated_rejected(self):
        self.client.force_authenticate(user=None)
        r = self.client.get(self.URL)
        self.assertEqual(r.status_code, 401)


# ============================================================
# 11. ENDPOINTS DASHBOARD — /api/v1/sessions/
# ============================================================

class ConnectionSessionAPITest(APITestCase):
    URL = '/api/v1/sessions/'

    def setUp(self):
        self.owner      = make_owner('owner1@example.com')
        self.other      = make_owner('owner2@example.com')
        self.client_obj = make_client(self.owner)
        self.other_client = make_client(self.other, mac='11:22:33:44:55:66', email='o2@x.com')
        self.client.force_authenticate(self.owner)

    def _session(self, owner, client_obj, **kwargs):
        return ConnectionSession.objects.create(
            owner=owner, client=client_obj,
            mac_address=client_obj.mac_address, **kwargs,
        )

    def test_list_only_own_sessions(self):
        self._session(self.owner, self.client_obj)
        self._session(self.other, self.other_client)
        r = self.client.get(self.URL)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.data), 1)

    def test_filter_active(self):
        self._session(self.owner, self.client_obj, is_active=True)
        self._session(self.owner, self.client_obj, is_active=False)
        r = self.client.get(self.URL, {'is_active': 'true'})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.data), 1)
        self.assertEqual(r.data[0]['status'], 'connecté')

    def test_filter_by_client(self):
        s = self._session(self.owner, self.client_obj)
        other_c = make_client(self.owner, mac='99:88:77:66:55:44', email='b@x.com')
        self._session(self.owner, other_c)
        r = self.client.get(self.URL, {'client': self.client_obj.id})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.data), 1)
        self.assertEqual(r.data[0]['id'], s.id)

    def test_retrieve_includes_expected_fields(self):
        s = self._session(
            self.owner, self.client_obj,
            uptime_seconds=180,
            session_timeout_seconds=14400,
            mikrotik_session_id='*TEST',
            disconnect_cause='session-timeout',
            is_active=False,
        )
        r = self.client.get(f'{self.URL}{s.id}/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data['session_timeout_seconds'], 14400)
        # disconnect_cause n'est plus exposé dans le serializer.
        # On vérifie le status calculé à la place.
        self.assertEqual(r.data['status'], 'déconnecté')
        self.assertEqual(r.data['duration_seconds'], 180)

    def test_unauthenticated_rejected(self):
        self.client.force_authenticate(user=None)
        r = self.client.get(self.URL)
        self.assertEqual(r.status_code, 401)


# ============================================================
# 12. ENDPOINTS DASHBOARD — /api/v1/tracking-analytics/
# ============================================================

class SessionAnalyticsAPITest(APITestCase):
    BASE_URL = '/api/v1/tracking-analytics/'

    def setUp(self):
        self.owner      = make_owner('a@x.com')
        self.other      = make_owner('b@x.com')
        self.client_obj = make_client(self.owner)
        self.client.force_authenticate(self.owner)
        self.plan = TicketPlan.objects.create(
            owner=self.owner, name='Pass 1h', price_fcfa=200, duration_minutes=60,
        )

    def _session(self, owner=None, **kwargs):
        owner = owner or self.owner
        client_obj = (
            self.client_obj if owner == self.owner
            else make_client(owner, mac='AA:11:22:33:44:55', email='z@x.com')
        )
        return ConnectionSession.objects.create(
            owner=owner,
            client=client_obj,
            mac_address=client_obj.mac_address,
            **kwargs,
        )

    def test_overview(self):
        s1 = self._session(uptime_seconds=300, bytes_downloaded=1024 * 1024)
        s1.ticket_plan = self.plan
        s1.save()
        self._session(is_active=False, uptime_seconds=600)

        r = self.client.get(f'{self.BASE_URL}overview/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data['total_sessions'], 2)
        self.assertEqual(r.data['active_sessions'], 1)

    def test_overview_owner_isolation(self):
        oc = make_client(self.other, mac='66:55:44:33:22:11', email='c@x.com')
        ConnectionSession.objects.create(owner=self.other, client=oc, mac_address=oc.mac_address)
        r = self.client.get(f'{self.BASE_URL}overview/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data['total_sessions'], 0)

    def test_by_day(self):
        self._session()
        self._session()
        r = self.client.get(f'{self.BASE_URL}by-day/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(sum(r.data['data']), 2)

    def test_by_hour(self):
        self._session()
        r = self.client.get(f'{self.BASE_URL}by-hour/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.data['labels']), 24)
        self.assertEqual(sum(r.data['data']), 1)

    def test_top_clients(self):
        self._session(uptime_seconds=100, bytes_downloaded=1024 * 1024)
        self._session(uptime_seconds=200, bytes_uploaded=2 * 1024 * 1024)
        r = self.client.get(f'{self.BASE_URL}top-clients/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data[0]['sessions_count'], 2)

    def test_unauthenticated_rejected(self):
        self.client.force_authenticate(user=None)
        r = self.client.get(f'{self.BASE_URL}overview/')
        self.assertEqual(r.status_code, 401)
