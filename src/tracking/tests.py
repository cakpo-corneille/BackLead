"""
Tests complets pour l'app tracking.

Couvre :
- Parsers MikroTik (uptime / limit)
- Modèles : TicketPlan & ConnectionSession (propriétés calculées)
- Services : handle_heartbeat (création / update / erreurs / matching plan),
            close_session, close_stale_sessions, match_ticket_plan
- Tasks Celery : cleanup_stale_sessions_task
- Endpoints publics : /tracking/heartbeat, /tracking/end
- Endpoints owner : /ticket-plans, /sessions, /session-analytics
"""
import uuid
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from rest_framework import status
from rest_framework.test import APITestCase, APIClient

from core_data.models import FormSchema, OwnerClient
from tracking.models import (
    TicketPlan,
    ConnectionSession,
    parse_mikrotik_uptime,
    parse_mikrotik_limit,
)
from tracking.services import (
    handle_heartbeat,
    match_ticket_plan,
    close_session,
    close_stale_sessions,
)
from tracking.tasks import cleanup_stale_sessions_task


User = get_user_model()


# ============================================================
# Helpers
# ============================================================

def make_owner(email='owner@example.com', password='Pass1234!'):
    return User.objects.create_user(email=email, password=password)


def make_client(owner, mac='AA:BB:CC:DD:EE:FF', email='lead@example.com', phone=None):
    return OwnerClient.objects.create(
        owner=owner,
        mac_address=mac,
        payload={'email': email, 'phone': phone},
        email=email,
        phone=phone,
    )


def get_public_key(owner):
    """FormSchema est créé par signal sur User. On récupère sa public_key."""
    return FormSchema.objects.get(owner=owner).public_key


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

    def test_empty_returns_zero(self):
        self.assertEqual(parse_mikrotik_uptime(''), 0)
        self.assertEqual(parse_mikrotik_uptime(None), 0)

    def test_garbage_returns_zero(self):
        self.assertEqual(parse_mikrotik_uptime('abc'), 0)


class ParseMikrotikLimitTest(TestCase):

    def test_megabytes(self):
        self.assertEqual(parse_mikrotik_limit('10M'), 10 * 1024 ** 2)

    def test_kilobytes(self):
        self.assertEqual(parse_mikrotik_limit('512k'), 512 * 1024)

    def test_gigabytes(self):
        self.assertEqual(parse_mikrotik_limit('2G'), 2 * 1024 ** 3)

    def test_unlimited_dashes(self):
        self.assertIsNone(parse_mikrotik_limit('---'))

    def test_unlimited_zero(self):
        self.assertIsNone(parse_mikrotik_limit('0'))

    def test_empty(self):
        self.assertIsNone(parse_mikrotik_limit(''))
        self.assertIsNone(parse_mikrotik_limit(None))

    def test_raw_int_string(self):
        self.assertEqual(parse_mikrotik_limit('1024'), 1024)

    def test_invalid(self):
        self.assertIsNone(parse_mikrotik_limit('abc'))


# ============================================================
# 2. MODELS
# ============================================================

class TicketPlanModelTest(TestCase):

    def setUp(self):
        self.owner = make_owner()

    def test_str(self):
        p = TicketPlan.objects.create(
            owner=self.owner, name='1h', price_fcfa=200, duration_minutes=60,
        )
        self.assertIn('1h', str(p))
        self.assertIn('200', str(p))

    def test_limits_in_bytes(self):
        p = TicketPlan.objects.create(
            owner=self.owner, name='Pack', price_fcfa=500,
            duration_minutes=120, download_limit_mb=100, upload_limit_mb=50,
        )
        self.assertEqual(p.download_limit_bytes, 100 * 1024 * 1024)
        self.assertEqual(p.upload_limit_bytes, 50 * 1024 * 1024)

    def test_unlimited_returns_none(self):
        p = TicketPlan.objects.create(
            owner=self.owner, name='Free', price_fcfa=0, duration_minutes=30,
        )
        self.assertIsNone(p.download_limit_bytes)
        self.assertIsNone(p.upload_limit_bytes)

    def test_default_active(self):
        p = TicketPlan.objects.create(
            owner=self.owner, name='X', price_fcfa=100, duration_minutes=15,
        )
        self.assertTrue(p.is_active)


class ConnectionSessionModelTest(TestCase):

    def setUp(self):
        self.owner = make_owner()
        self.client_obj = make_client(self.owner)

    def _new_session(self, **kwargs):
        return ConnectionSession.objects.create(
            owner=self.owner, client=self.client_obj,
            mac_address='AA:BB:CC:DD:EE:FF',
            **kwargs,
        )

    def test_duration_seconds_uses_uptime_when_active(self):
        s = self._new_session(uptime_seconds=125)
        self.assertEqual(s.duration_seconds, 125)

    def test_duration_seconds_uses_ended_at(self):
        s = self._new_session(uptime_seconds=999)
        s.ended_at = s.started_at + timedelta(seconds=300)
        s.save()
        self.assertEqual(s.duration_seconds, 300)

    def test_duration_human(self):
        s = self._new_session(uptime_seconds=3725)  # 1h 2m 5s
        self.assertEqual(s.duration_human, '1h 2m 5s')

    def test_duration_human_seconds_only(self):
        s = self._new_session(uptime_seconds=42)
        self.assertEqual(s.duration_human, '42s')

    def test_data_properties_in_mb(self):
        s = self._new_session(
            bytes_downloaded=2 * 1024 * 1024,
            bytes_uploaded=1024 * 1024,
        )
        self.assertEqual(s.download_mb, 2.0)
        self.assertEqual(s.upload_mb, 1.0)
        self.assertEqual(s.total_mb, 3.0)


# ============================================================
# 3. SERVICES
# ============================================================

class HandleHeartbeatTest(TestCase):

    def setUp(self):
        self.owner = make_owner()
        self.client_obj = make_client(self.owner)
        self.public_key = get_public_key(self.owner)

    def _payload(self, **overrides):
        base = {
            'public_key': str(self.public_key),
            'mac_address': 'AA:BB:CC:DD:EE:FF',
            'uptime': '5m',
            'bytes_in': '1048576',
            'bytes_out': '524288',
            'rx_limit': '---',
            'tx_limit': '---',
        }
        base.update(overrides)
        return base

    def test_creates_new_session(self):
        session, created = handle_heartbeat(self._payload())
        self.assertTrue(created)
        self.assertEqual(session.owner, self.owner)
        self.assertEqual(session.client, self.client_obj)
        self.assertEqual(session.uptime_seconds, 300)
        self.assertEqual(session.bytes_downloaded, 1048576)
        self.assertEqual(session.bytes_uploaded, 524288)
        self.assertTrue(session.is_active)

    def test_updates_existing_session_via_session_key(self):
        s1, _ = handle_heartbeat(self._payload())
        s2, created = handle_heartbeat(self._payload(
            session_key=str(s1.session_key),
            uptime='10m',
            bytes_in='2097152',
        ))
        self.assertFalse(created)
        self.assertEqual(s1.pk, s2.pk)
        self.assertEqual(s2.uptime_seconds, 600)
        self.assertEqual(s2.bytes_downloaded, 2097152)

    def test_orphan_session_key_creates_new(self):
        """Si la session_key envoyée n'existe plus, on doit fallback en création."""
        _, created = handle_heartbeat(self._payload(
            session_key=str(uuid.uuid4()),
        ))
        self.assertTrue(created)

    def test_invalid_public_key_raises(self):
        with self.assertRaises(ValueError) as ctx:
            handle_heartbeat(self._payload(public_key=str(uuid.uuid4())))
        self.assertIn('public_key', str(ctx.exception))

    def test_missing_client_raises(self):
        with self.assertRaises(ValueError) as ctx:
            handle_heartbeat(self._payload(mac_address='11:22:33:44:55:66'))
        self.assertIn('Client', str(ctx.exception))

    def test_mac_normalized_uppercase(self):
        session, _ = handle_heartbeat(self._payload(
            mac_address='aa:bb:cc:dd:ee:ff',
        ))
        self.assertEqual(session.mac_address, 'AA:BB:CC:DD:EE:FF')

    def test_matches_plan_by_limits(self):
        plan = TicketPlan.objects.create(
            owner=self.owner, name='10MB', price_fcfa=100,
            duration_minutes=60, download_limit_mb=10, upload_limit_mb=5,
        )
        session, _ = handle_heartbeat(self._payload(
            rx_limit='10M', tx_limit='5M',
        ))
        self.assertEqual(session.ticket_plan, plan)

    def test_no_plan_match_leaves_null(self):
        session, _ = handle_heartbeat(self._payload(
            rx_limit='99M', tx_limit='99M',
        ))
        self.assertIsNone(session.ticket_plan)


class MatchTicketPlanTest(TestCase):

    def setUp(self):
        self.owner = make_owner()

    def test_match_by_limits_strict(self):
        p = TicketPlan.objects.create(
            owner=self.owner, name='A', price_fcfa=100,
            duration_minutes=60, download_limit_mb=10, upload_limit_mb=5,
        )
        m = match_ticket_plan(
            owner=self.owner,
            download_limit_bytes=10 * 1024 ** 2,
            upload_limit_bytes=5 * 1024 ** 2,
            uptime_seconds=300,
        )
        self.assertEqual(m, p)

    def test_no_match_by_limits(self):
        TicketPlan.objects.create(
            owner=self.owner, name='A', price_fcfa=100,
            duration_minutes=60, download_limit_mb=10, upload_limit_mb=5,
        )
        m = match_ticket_plan(
            owner=self.owner,
            download_limit_bytes=99 * 1024 ** 2,
            upload_limit_bytes=99 * 1024 ** 2,
            uptime_seconds=0,
        )
        self.assertIsNone(m)

    def test_fallback_by_duration(self):
        p1 = TicketPlan.objects.create(
            owner=self.owner, name='15min', price_fcfa=50, duration_minutes=15,
        )
        p2 = TicketPlan.objects.create(
            owner=self.owner, name='1h', price_fcfa=200, duration_minutes=60,
        )
        m = match_ticket_plan(
            owner=self.owner,
            download_limit_bytes=None,
            upload_limit_bytes=None,
            uptime_seconds=3500,  # ~58min → plus proche de 1h
        )
        self.assertEqual(m, p2)
        m2 = match_ticket_plan(
            owner=self.owner,
            download_limit_bytes=None,
            upload_limit_bytes=None,
            uptime_seconds=600,  # 10min → plus proche de 15min
        )
        self.assertEqual(m2, p1)

    def test_inactive_plan_ignored(self):
        TicketPlan.objects.create(
            owner=self.owner, name='Old', price_fcfa=100,
            duration_minutes=60, download_limit_mb=10, upload_limit_mb=5,
            is_active=False,
        )
        m = match_ticket_plan(
            owner=self.owner,
            download_limit_bytes=10 * 1024 ** 2,
            upload_limit_bytes=5 * 1024 ** 2,
            uptime_seconds=0,
        )
        self.assertIsNone(m)

    def test_zero_uptime_fallback_returns_none(self):
        TicketPlan.objects.create(
            owner=self.owner, name='1h', price_fcfa=200, duration_minutes=60,
        )
        m = match_ticket_plan(
            owner=self.owner,
            download_limit_bytes=None,
            upload_limit_bytes=None,
            uptime_seconds=0,
        )
        self.assertIsNone(m)

    def test_owner_isolation(self):
        other = make_owner('other@example.com')
        TicketPlan.objects.create(
            owner=other, name='Other', price_fcfa=100,
            duration_minutes=60, download_limit_mb=10, upload_limit_mb=5,
        )
        m = match_ticket_plan(
            owner=self.owner,
            download_limit_bytes=10 * 1024 ** 2,
            upload_limit_bytes=5 * 1024 ** 2,
            uptime_seconds=0,
        )
        self.assertIsNone(m)


class CloseSessionTest(TestCase):

    def setUp(self):
        self.owner = make_owner()
        self.client_obj = make_client(self.owner)
        self.session = ConnectionSession.objects.create(
            owner=self.owner, client=self.client_obj,
            mac_address='AA:BB:CC:DD:EE:FF',
        )

    def test_closes_active_session(self):
        n = close_session(str(self.session.session_key))
        self.assertEqual(n, 1)
        self.session.refresh_from_db()
        self.assertFalse(self.session.is_active)
        self.assertIsNotNone(self.session.ended_at)

    def test_idempotent(self):
        close_session(str(self.session.session_key))
        n = close_session(str(self.session.session_key))
        self.assertEqual(n, 0)

    def test_unknown_key_no_error(self):
        n = close_session(str(uuid.uuid4()))
        self.assertEqual(n, 0)


class CloseStaleSessionsTest(TestCase):

    def setUp(self):
        self.owner = make_owner()
        self.client_obj = make_client(self.owner)

    def _session(self, last_heartbeat_minutes_ago, is_active=True):
        s = ConnectionSession.objects.create(
            owner=self.owner, client=self.client_obj,
            mac_address='AA:BB:CC:DD:EE:FF',
            is_active=is_active,
        )
        # last_heartbeat est auto_now → on l'écrase via update()
        new_ts = timezone.now() - timedelta(minutes=last_heartbeat_minutes_ago)
        ConnectionSession.objects.filter(pk=s.pk).update(last_heartbeat=new_ts)
        s.refresh_from_db()
        return s

    def test_closes_only_stale(self):
        fresh = self._session(2)
        stale = self._session(15)
        self._session(20, is_active=False)  # déjà fermée → ignorée

        n = close_stale_sessions(threshold_minutes=10)
        self.assertEqual(n, 1)

        fresh.refresh_from_db()
        stale.refresh_from_db()
        self.assertTrue(fresh.is_active)
        self.assertFalse(stale.is_active)
        self.assertEqual(stale.ended_at, stale.last_heartbeat)

    def test_threshold_respected(self):
        self._session(7)
        self.assertEqual(close_stale_sessions(threshold_minutes=10), 0)
        self.assertEqual(close_stale_sessions(threshold_minutes=5), 1)


# ============================================================
# 4. CELERY TASK
# ============================================================

@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
class CleanupStaleSessionsTaskTest(TestCase):

    def test_task_invokes_close_stale(self):
        owner = make_owner()
        c = make_client(owner)
        s = ConnectionSession.objects.create(
            owner=owner, client=c, mac_address='AA:BB:CC:DD:EE:FF',
        )
        ConnectionSession.objects.filter(pk=s.pk).update(
            last_heartbeat=timezone.now() - timedelta(minutes=20)
        )

        result = cleanup_stale_sessions_task.apply().get()
        self.assertEqual(result, 1)
        s.refresh_from_db()
        self.assertFalse(s.is_active)


# ============================================================
# 5. ENDPOINTS PUBLICS — /tracking/heartbeat & /tracking/end
# ============================================================

class TrackingPublicEndpointsTest(APITestCase):

    def setUp(self):
        self.owner = make_owner()
        self.client_obj = make_client(self.owner)
        self.public_key = get_public_key(self.owner)
        self.heartbeat_url = '/api/v1/tracking/heartbeat/'
        self.end_url = '/api/v1/tracking/end/'

    def test_heartbeat_creates_session(self):
        r = self.client.post(self.heartbeat_url, {
            'public_key': str(self.public_key),
            'mac_address': 'AA:BB:CC:DD:EE:FF',
            'uptime': '1m',
            'bytes_in': '100',
            'bytes_out': '50',
        }, format='json', HTTP_USER_AGENT='Mozilla/5.0 (TestPhone)')
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        self.assertTrue(r.data['ok'])
        self.assertTrue(r.data['created'])
        self.assertIn('session_key', r.data)
        s = ConnectionSession.objects.get(session_key=r.data['session_key'])
        self.assertEqual(s.user_agent, 'Mozilla/5.0 (TestPhone)')

    def test_heartbeat_user_agent_truncated(self):
        long_ua = 'A' * 1000
        r = self.client.post(self.heartbeat_url, {
            'public_key': str(self.public_key),
            'mac_address': 'AA:BB:CC:DD:EE:FF',
        }, format='json', HTTP_USER_AGENT=long_ua)
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        s = ConnectionSession.objects.get(session_key=r.data['session_key'])
        self.assertEqual(len(s.user_agent), 512)

    def test_heartbeat_backfills_user_agent_on_update(self):
        """Si la 1ʳᵉ session n'a pas de UA, un heartbeat suivant le renseigne."""
        s = ConnectionSession.objects.create(
            owner=self.owner, client=self.client_obj,
            mac_address='AA:BB:CC:DD:EE:FF',
        )
        self.assertEqual(s.user_agent, '')
        r = self.client.post(self.heartbeat_url, {
            'public_key': str(self.public_key),
            'mac_address': 'AA:BB:CC:DD:EE:FF',
            'session_key': str(s.session_key),
        }, format='json', HTTP_USER_AGENT='Chrome/120')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        s.refresh_from_db()
        self.assertEqual(s.user_agent, 'Chrome/120')

    def test_heartbeat_updates_existing(self):
        r1 = self.client.post(self.heartbeat_url, {
            'public_key': str(self.public_key),
            'mac_address': 'AA:BB:CC:DD:EE:FF',
            'uptime': '1m',
        }, format='json')
        sk = r1.data['session_key']
        r2 = self.client.post(self.heartbeat_url, {
            'public_key': str(self.public_key),
            'mac_address': 'AA:BB:CC:DD:EE:FF',
            'session_key': sk,
            'uptime': '2m',
        }, format='json')
        self.assertEqual(r2.status_code, status.HTTP_200_OK)
        self.assertFalse(r2.data['created'])
        self.assertEqual(r2.data['session_key'], sk)

    def test_heartbeat_invalid_mac(self):
        r = self.client.post(self.heartbeat_url, {
            'public_key': str(self.public_key),
            'mac_address': 'not-a-mac',
        }, format='json')
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_heartbeat_missing_public_key(self):
        r = self.client.post(self.heartbeat_url, {
            'mac_address': 'AA:BB:CC:DD:EE:FF',
        }, format='json')
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_heartbeat_unknown_public_key(self):
        r = self.client.post(self.heartbeat_url, {
            'public_key': str(uuid.uuid4()),
            'mac_address': 'AA:BB:CC:DD:EE:FF',
        }, format='json')
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_heartbeat_unknown_client(self):
        r = self.client.post(self.heartbeat_url, {
            'public_key': str(self.public_key),
            'mac_address': '11:22:33:44:55:66',
        }, format='json')
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('Client', r.data['detail'])

    def test_end_session(self):
        r = self.client.post(self.heartbeat_url, {
            'public_key': str(self.public_key),
            'mac_address': 'AA:BB:CC:DD:EE:FF',
        }, format='json')
        sk = r.data['session_key']
        r2 = self.client.post(self.end_url, {'session_key': sk}, format='json')
        self.assertEqual(r2.status_code, status.HTTP_200_OK)
        self.assertEqual(r2.data['closed'], 1)

        s = ConnectionSession.objects.get(session_key=sk)
        self.assertFalse(s.is_active)

    def test_end_session_invalid(self):
        r = self.client.post(self.end_url, {'session_key': 'not-a-uuid'}, format='json')
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_end_session_no_auth_required(self):
        """Le tracker public doit fonctionner sans token JWT."""
        r = self.client.post(self.end_url, {'session_key': str(uuid.uuid4())}, format='json')
        self.assertEqual(r.status_code, status.HTTP_200_OK)


# ============================================================
# 6. ENDPOINTS DASHBOARD — /ticket-plans
# ============================================================

class TicketPlanAPITest(APITestCase):

    def setUp(self):
        self.owner = make_owner('owner1@example.com')
        self.other = make_owner('owner2@example.com')
        self.client.force_authenticate(self.owner)
        self.url = '/api/v1/ticket-plans/'

    def test_list_only_own_plans(self):
        TicketPlan.objects.create(
            owner=self.owner, name='Mine', price_fcfa=100, duration_minutes=60,
        )
        TicketPlan.objects.create(
            owner=self.other, name='Theirs', price_fcfa=100, duration_minutes=60,
        )
        r = self.client.get(self.url)
        self.assertEqual(r.status_code, 200)
        names = [p['name'] for p in r.data]
        self.assertIn('Mine', names)
        self.assertNotIn('Theirs', names)

    def test_create_assigns_owner(self):
        r = self.client.post(self.url, {
            'name': '1h', 'price_fcfa': 200, 'duration_minutes': 60,
            'download_limit_mb': 100, 'upload_limit_mb': 50,
        }, format='json')
        self.assertEqual(r.status_code, 201)
        plan = TicketPlan.objects.get(name='1h')
        self.assertEqual(plan.owner, self.owner)

    def test_validate_negative_price(self):
        r = self.client.post(self.url, {
            'name': 'X', 'price_fcfa': -1, 'duration_minutes': 60,
        }, format='json')
        self.assertEqual(r.status_code, 400)

    def test_validate_zero_duration(self):
        r = self.client.post(self.url, {
            'name': 'X', 'price_fcfa': 100, 'duration_minutes': 0,
        }, format='json')
        self.assertEqual(r.status_code, 400)

    def test_update_own_plan(self):
        plan = TicketPlan.objects.create(
            owner=self.owner, name='Old', price_fcfa=100, duration_minutes=60,
        )
        r = self.client.patch(f'{self.url}{plan.id}/', {'name': 'New'}, format='json')
        self.assertEqual(r.status_code, 200)
        plan.refresh_from_db()
        self.assertEqual(plan.name, 'New')

    def test_cannot_access_others_plan(self):
        plan = TicketPlan.objects.create(
            owner=self.other, name='Theirs', price_fcfa=100, duration_minutes=60,
        )
        r = self.client.get(f'{self.url}{plan.id}/')
        self.assertEqual(r.status_code, 404)

    def test_delete_own_plan(self):
        plan = TicketPlan.objects.create(
            owner=self.owner, name='X', price_fcfa=100, duration_minutes=60,
        )
        r = self.client.delete(f'{self.url}{plan.id}/')
        self.assertEqual(r.status_code, 204)
        self.assertFalse(TicketPlan.objects.filter(pk=plan.pk).exists())

    def test_unauthenticated_rejected(self):
        self.client.force_authenticate(None)
        r = self.client.get(self.url)
        self.assertEqual(r.status_code, 401)


# ============================================================
# 7. ENDPOINTS DASHBOARD — /sessions
# ============================================================

class ConnectionSessionAPITest(APITestCase):

    def setUp(self):
        self.owner = make_owner('owner1@example.com')
        self.other = make_owner('owner2@example.com')
        self.client_obj = make_client(self.owner)
        self.other_client = make_client(self.other, mac='11:22:33:44:55:66', email='o2@x.com')
        self.client.force_authenticate(self.owner)
        self.url = '/api/v1/sessions/'

    def _session(self, owner, client_obj, **kwargs):
        return ConnectionSession.objects.create(
            owner=owner, client=client_obj,
            mac_address=client_obj.mac_address, **kwargs,
        )

    def test_list_only_own_sessions(self):
        self._session(self.owner, self.client_obj)
        self._session(self.other, self.other_client)
        r = self.client.get(self.url)
        self.assertEqual(r.status_code, 200)
        results = r.data
        self.assertEqual(len(results), 1)

    def test_filter_active(self):
        self._session(self.owner, self.client_obj, is_active=True)
        self._session(self.owner, self.client_obj, is_active=False)
        r = self.client.get(self.url, {'is_active': 'true'})
        results = r.data
        self.assertEqual(len(results), 1)
        self.assertTrue(results[0]['is_active'])

    def test_filter_by_client(self):
        s = self._session(self.owner, self.client_obj)
        other_c = make_client(self.owner, mac='99:88:77:66:55:44', email='b@x.com')
        self._session(self.owner, other_c)
        r = self.client.get(self.url, {'client': self.client_obj.id})
        results = r.data
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['id'], s.id)

    def test_retrieve(self):
        s = self._session(self.owner, self.client_obj, uptime_seconds=180)
        r = self.client.get(f'{self.url}{s.id}/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data['duration_seconds'], 180)
        self.assertEqual(r.data['duration_human'], '3m 0s')

    def test_unauthenticated_rejected(self):
        self.client.force_authenticate(None)
        r = self.client.get(self.url)
        self.assertEqual(r.status_code, 401)


# ============================================================
# 8. ENDPOINTS DASHBOARD — /session-analytics
# ============================================================

class SessionAnalyticsAPITest(APITestCase):

    def setUp(self):
        self.owner = make_owner('a@x.com')
        self.other = make_owner('b@x.com')
        self.client_obj = make_client(self.owner)
        self.client.force_authenticate(self.owner)
        self.plan = TicketPlan.objects.create(
            owner=self.owner, name='1h', price_fcfa=200, duration_minutes=60,
        )

    def _session(self, owner=None, **kwargs):
        return ConnectionSession.objects.create(
            owner=owner or self.owner,
            client=self.client_obj if (owner or self.owner) == self.owner else make_client(owner, mac='AA:11:22:33:44:55', email='z@x.com'),
            mac_address='AA:BB:CC:DD:EE:FF',
            **kwargs,
        )

    def test_overview(self):
        s1 = self._session(uptime_seconds=300, bytes_downloaded=1024 * 1024)
        s1.ticket_plan = self.plan
        s1.save()
        self._session(is_active=False, uptime_seconds=600)

        r = self.client.get('/api/v1/session-analytics/overview/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data['total_sessions'], 2)
        self.assertEqual(r.data['active_sessions'], 1)
        self.assertEqual(r.data['avg_session_seconds'], 450)
        self.assertEqual(r.data['estimated_revenue_today_fcfa'], 200)

    def test_overview_owner_isolation(self):
        oc = make_client(self.other, mac='66:55:44:33:22:11', email='c@x.com')
        ConnectionSession.objects.create(
            owner=self.other, client=oc, mac_address=oc.mac_address,
        )
        r = self.client.get('/api/v1/session-analytics/overview/')
        self.assertEqual(r.data['total_sessions'], 0)

    def test_by_day(self):
        self._session(uptime_seconds=10)
        self._session(uptime_seconds=20)
        r = self.client.get('/api/v1/session-analytics/by-day/')
        self.assertEqual(r.status_code, 200)
        self.assertIn('labels', r.data)
        self.assertIn('data', r.data)
        self.assertEqual(sum(r.data['data']), 2)

    def test_by_day_invalid_days_param_uses_default(self):
        self._session()
        r = self.client.get('/api/v1/session-analytics/by-day/', {'days': 'abc'})
        self.assertEqual(r.status_code, 200)

    def test_by_hour(self):
        self._session()
        r = self.client.get('/api/v1/session-analytics/by-hour/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.data['labels']), 24)
        self.assertEqual(len(r.data['data']), 24)
        self.assertEqual(sum(r.data['data']), 1)

    def test_top_clients(self):
        self._session(uptime_seconds=100, bytes_downloaded=1024 * 1024)
        self._session(uptime_seconds=200, bytes_uploaded=2 * 1024 * 1024)
        r = self.client.get('/api/v1/session-analytics/top-clients/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.data), 1)
        self.assertEqual(r.data[0]['sessions_count'], 2)
        self.assertEqual(r.data[0]['total_seconds'], 300)
        self.assertEqual(r.data[0]['client_id'], self.client_obj.id)

    def test_unauthenticated_rejected(self):
        self.client.force_authenticate(None)
        r = self.client.get('/api/v1/session-analytics/overview/')
        self.assertEqual(r.status_code, 401)
