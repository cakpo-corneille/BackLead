"""
Tests complets pour l'app tracking.

Couvre :
- Parsers MikroTik (uptime)
- Modèles : TicketPlan, MikroTikRouter (chiffrement mdp), ConnectionSession
- Services : handle_heartbeat, close_session, close_stale_sessions,
             match_ticket_plan (par session_timeout uniquement)
- mikrotik_api : test_router_connection, get_active_clients, sync_router
- Tasks Celery : sync_all_mikrotik_routers, close_stale_sessions
- Endpoints publics : /tracking/heartbeat, /tracking/end
- Endpoints owner : /ticket-plans, /routers, /sessions, /session-analytics
"""
import uuid
from datetime import timedelta
from unittest.mock import patch, MagicMock

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone

from rest_framework import status
from rest_framework.test import APITestCase

from core_data.models import FormSchema, OwnerClient
from tracking.models import (
    TicketPlan,
    MikroTikRouter,
    ConnectionSession,
    parse_mikrotik_uptime,
)
from tracking.services import (
    handle_heartbeat,
    match_ticket_plan,
    close_session,
    close_stale_sessions,
)
from tracking.tasks import sync_all_mikrotik_routers, close_stale_sessions as close_stale_task


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


def make_router(owner, host='192.168.88.1', password='secret'):
    r = MikroTikRouter(
        owner=owner,
        name='Routeur test',
        host=host,
        port=8728,
        username='api-user',
    )
    r.set_password(password)
    r.save()
    return r


# ============================================================
# 1. PARSERS MikroTik
# ============================================================

class ParseMikrotikUptimeTest(TestCase):
    """
    parse_mikrotik_uptime est le seul parser conservé en v2.0.
    parse_mikrotik_limit a été supprimé avec les champs rx/tx-limit.
    """

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

    def test_empty_returns_zero(self):
        self.assertEqual(parse_mikrotik_uptime(''), 0)
        self.assertEqual(parse_mikrotik_uptime(None), 0)

    def test_garbage_returns_zero(self):
        self.assertEqual(parse_mikrotik_uptime('abc'), 0)

    def test_session_timeout_4h(self):
        """Cas réel : ticket de 4h → 14400 secondes."""
        self.assertEqual(parse_mikrotik_uptime('4h'), 14400)

    def test_session_timeout_12h(self):
        """Cas réel : ticket de 12h → 43200 secondes."""
        self.assertEqual(parse_mikrotik_uptime('12h'), 43200)


# ============================================================
# 2. MODELS
# ============================================================

class TicketPlanModelTest(TestCase):
    """
    En v2.0, TicketPlan n'a plus de champs download/upload_limit_mb.
    Un plan = nom + durée + prix uniquement.
    """

    def setUp(self):
        self.owner = make_owner()

    def test_str(self):
        p = TicketPlan.objects.create(
            owner=self.owner, name='Pass 1h', price_fcfa=200, duration_minutes=60,
        )
        self.assertIn('Pass 1h', str(p))
        self.assertIn('200', str(p))

    def test_default_active(self):
        p = TicketPlan.objects.create(
            owner=self.owner, name='X', price_fcfa=100, duration_minutes=15,
        )
        self.assertTrue(p.is_active)

    def test_create_minimal(self):
        """Création sans aucun champ optionnel — ne doit pas planter."""
        p = TicketPlan.objects.create(
            owner=self.owner, name='Pass 4h', price_fcfa=500, duration_minutes=240,
        )
        self.assertEqual(p.duration_minutes, 240)
        self.assertEqual(p.price_fcfa, 500)


class MikroTikRouterModelTest(TestCase):
    """
    Tests du modèle MikroTikRouter — entièrement nouveau en v2.0.
    Focus sur le chiffrement/déchiffrement du mot de passe.
    """

    def setUp(self):
        self.owner = make_owner()

    def test_password_is_encrypted_in_db(self):
        """Le mot de passe stocké en base ne doit jamais être en clair."""
        r = make_router(self.owner, password='monsecret')
        raw_stored = bytes(r._password_encrypted)
        self.assertNotIn(b'monsecret', raw_stored)

    def test_get_password_returns_original(self):
        """Déchiffrement doit retrouver le mot de passe exact."""
        r = make_router(self.owner, password='monsecret')
        self.assertEqual(r.get_password(), 'monsecret')

    def test_set_password_overrides_previous(self):
        r = make_router(self.owner, password='ancien')
        r.set_password('nouveau')
        r.save()
        r.refresh_from_db()
        self.assertEqual(r.get_password(), 'nouveau')

    def test_default_port(self):
        r = make_router(self.owner)
        self.assertEqual(r.port, 8728)

    def test_default_is_active(self):
        r = make_router(self.owner)
        self.assertTrue(r.is_active)

    def test_last_error_default_empty(self):
        r = make_router(self.owner)
        self.assertEqual(r.last_error, '')

    def test_str(self):
        r = make_router(self.owner, host='10.0.0.1')
        self.assertIn('10.0.0.1', str(r))

    def test_last_synced_at_none_by_default(self):
        r = make_router(self.owner)
        self.assertIsNone(r.last_synced_at)


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

    def test_session_timeout_seconds_default_zero(self):
        """Nouveau champ v2.0 — doit valoir 0 par défaut."""
        s = self._new_session()
        self.assertEqual(s.session_timeout_seconds, 0)

    def test_session_timeout_seconds_stored(self):
        """La durée totale du ticket doit être persistée correctement."""
        s = self._new_session(session_timeout_seconds=14400)
        s.refresh_from_db()
        self.assertEqual(s.session_timeout_seconds, 14400)

    def test_router_fk_nullable(self):
        """Le routeur source est optionnel (sessions créées avant config routeur)."""
        s = self._new_session()
        self.assertIsNone(s.router)


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
            'session_timeout': '4h',   # ← v2.0 : durée totale du ticket
            'bytes_in': '1048576',
            'bytes_out': '524288',
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

    def test_session_timeout_captured_on_creation(self):
        """session_timeout_seconds doit être capturé dès le 1er heartbeat."""
        session, _ = handle_heartbeat(self._payload(session_timeout='4h'))
        self.assertEqual(session.session_timeout_seconds, 14400)

    def test_session_timeout_1h(self):
        session, _ = handle_heartbeat(self._payload(session_timeout='1h'))
        self.assertEqual(session.session_timeout_seconds, 3600)

    def test_session_timeout_12h(self):
        session, _ = handle_heartbeat(self._payload(session_timeout='12h'))
        self.assertEqual(session.session_timeout_seconds, 43200)

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
        """session_key inconnue → fallback création."""
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
        session, _ = handle_heartbeat(self._payload(mac_address='aa:bb:cc:dd:ee:ff'))
        self.assertEqual(session.mac_address, 'AA:BB:CC:DD:EE:FF')

    def test_matches_plan_by_session_timeout(self):
        """v2.0 : identification du plan via session-timeout, pas rx/tx-limit."""
        plan = TicketPlan.objects.create(
            owner=self.owner, name='Pass 4h', price_fcfa=200, duration_minutes=240,
        )
        session, _ = handle_heartbeat(self._payload(session_timeout='4h'))
        self.assertEqual(session.ticket_plan, plan)

    def test_no_plan_match_when_no_timeout(self):
        """Sans session_timeout, ticket_plan reste null."""
        TicketPlan.objects.create(
            owner=self.owner, name='Pass 1h', price_fcfa=100, duration_minutes=60,
        )
        session, _ = handle_heartbeat(self._payload(session_timeout=''))
        self.assertIsNone(session.ticket_plan)


class MatchTicketPlanTest(TestCase):
    """
    v2.0 : match_ticket_plan prend uniquement (owner, session_timeout_seconds).
    Toute la logique rx/tx-limit a été supprimée.
    """

    def setUp(self):
        self.owner = make_owner()

    def test_match_exact_duration(self):
        """Ticket 4h = 14400s → plan 240 min."""
        p = TicketPlan.objects.create(
            owner=self.owner, name='Pass 4h', price_fcfa=200, duration_minutes=240,
        )
        m = match_ticket_plan(owner=self.owner, session_timeout_seconds=14400)
        self.assertEqual(m, p)

    def test_match_1h(self):
        p = TicketPlan.objects.create(
            owner=self.owner, name='Pass 1h', price_fcfa=100, duration_minutes=60,
        )
        m = match_ticket_plan(owner=self.owner, session_timeout_seconds=3600)
        self.assertEqual(m, p)

    def test_match_12h(self):
        p = TicketPlan.objects.create(
            owner=self.owner, name='Pass 12h', price_fcfa=500, duration_minutes=720,
        )
        m = match_ticket_plan(owner=self.owner, session_timeout_seconds=43200)
        self.assertEqual(m, p)

    def test_match_closest_plan(self):
        """Quand la durée ne correspond pas exactement, on prend le plus proche."""
        TicketPlan.objects.create(
            owner=self.owner, name='30min', price_fcfa=50, duration_minutes=30,
        )
        p2 = TicketPlan.objects.create(
            owner=self.owner, name='1h', price_fcfa=100, duration_minutes=60,
        )
        # 3500s ≈ 58min → plus proche de 60min que de 30min
        m = match_ticket_plan(owner=self.owner, session_timeout_seconds=3500)
        self.assertEqual(m, p2)

    def test_zero_session_timeout_returns_none(self):
        """Sans durée (ticket illimité ou non configuré), pas de plan détecté."""
        TicketPlan.objects.create(
            owner=self.owner, name='1h', price_fcfa=200, duration_minutes=60,
        )
        m = match_ticket_plan(owner=self.owner, session_timeout_seconds=0)
        self.assertIsNone(m)

    def test_negative_session_timeout_returns_none(self):
        m = match_ticket_plan(owner=self.owner, session_timeout_seconds=-1)
        self.assertIsNone(m)

    def test_inactive_plan_ignored(self):
        TicketPlan.objects.create(
            owner=self.owner, name='Old', price_fcfa=100,
            duration_minutes=60, is_active=False,
        )
        m = match_ticket_plan(owner=self.owner, session_timeout_seconds=3600)
        self.assertIsNone(m)

    def test_owner_isolation(self):
        """Un plan d'un autre owner ne doit jamais être retourné."""
        other = make_owner('other@example.com')
        TicketPlan.objects.create(
            owner=other, name='Autre', price_fcfa=100, duration_minutes=60,
        )
        m = match_ticket_plan(owner=self.owner, session_timeout_seconds=3600)
        self.assertIsNone(m)

    def test_no_plans_returns_none(self):
        m = match_ticket_plan(owner=self.owner, session_timeout_seconds=3600)
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
# 4. MIKROTIK API
# ============================================================

class SyncRouterTest(TestCase):
    """
    Tests de sync_router() — nouveau en v2.0.
    On mocke librouteros pour ne pas avoir besoin d'un vrai routeur.
    """

    def setUp(self):
        self.owner = make_owner()
        self.client_obj = make_client(self.owner, mac='AA:BB:CC:DD:EE:FF')
        self.router = make_router(self.owner)
        self.plan = TicketPlan.objects.create(
            owner=self.owner, name='Pass 4h', price_fcfa=200, duration_minutes=240,
        )

    def _fake_clients(self):
        """Simule la réponse de MikroTik pour un client actif."""
        return [{
            'mac-address': 'AA:BB:CC:DD:EE:FF',
            'user': 'TICKET123',
            'address': '192.168.88.10',
            'uptime': '30m',
            'session-timeout': '4h',
            'bytes-in': '5000000',
            'bytes-out': '1000000',
            'session-id': 'sid-001',
        }]

    @patch('tracking.mikrotik_api.router_connection')
    def test_updates_existing_session(self, mock_conn):
        """Un client déjà en base doit être mis à jour, pas recréé."""
        session = ConnectionSession.objects.create(
            owner=self.owner, client=self.client_obj,
            mac_address='AA:BB:CC:DD:EE:FF',
            is_active=True,
        )
        mock_api = MagicMock()
        mock_api.return_value.__enter__ = lambda s: mock_api
        mock_api.return_value.__exit__ = MagicMock(return_value=False)
        mock_api.__enter__ = lambda s: mock_api
        mock_api.__exit__ = MagicMock(return_value=False)

        with patch('tracking.mikrotik_api.get_active_clients', return_value=[{
            'mac_address': 'AA:BB:CC:DD:EE:FF',
            'username': 'TICKET123',
            'ip_address': '192.168.88.10',
            'uptime_seconds': 1800,
            'session_timeout_seconds': 14400,
            'bytes_downloaded': 5000000,
            'bytes_uploaded': 1000000,
            'session_id': 'sid-001',
        }]):
            mock_conn.return_value.__enter__ = MagicMock(return_value=mock_api)
            mock_conn.return_value.__exit__ = MagicMock(return_value=False)

            from tracking.mikrotik_api import sync_router
            stats = sync_router(self.router)

        self.assertEqual(stats['updated'], 1)
        self.assertEqual(stats['created'], 0)
        self.assertEqual(stats['closed'], 0)

        session.refresh_from_db()
        self.assertEqual(session.uptime_seconds, 1800)
        self.assertEqual(session.bytes_downloaded, 5000000)

    @patch('tracking.mikrotik_api.router_connection')
    def test_closes_session_when_client_gone(self, mock_conn):
        """Client absent de MikroTik → session fermée."""
        session = ConnectionSession.objects.create(
            owner=self.owner, client=self.client_obj,
            mac_address='AA:BB:CC:DD:EE:FF',
            is_active=True,
        )
        with patch('tracking.mikrotik_api.get_active_clients', return_value=[]):
            mock_conn.return_value.__enter__ = MagicMock(return_value=MagicMock())
            mock_conn.return_value.__exit__ = MagicMock(return_value=False)

            from tracking.mikrotik_api import sync_router
            stats = sync_router(self.router)

        self.assertEqual(stats['closed'], 1)
        session.refresh_from_db()
        self.assertFalse(session.is_active)
        self.assertIsNotNone(session.ended_at)

    def test_connection_error_updates_last_error(self):
        """Routeur injoignable → last_error renseigné, pas d'exception globale."""
        with patch('tracking.mikrotik_api.router_connection',
                   side_effect=ConnectionError("Timeout")):
            from tracking.mikrotik_api import sync_router
            stats = sync_router(self.router)

        self.assertEqual(stats, {'updated': 0, 'created': 0, 'closed': 0})
        self.router.refresh_from_db()
        self.assertIn('Timeout', self.router.last_error)


class TestRouterConnectionTest(TestCase):
    """Tests de test_router_connection()."""

    def setUp(self):
        self.owner = make_owner()
        self.router = make_router(self.owner)

    def test_returns_ok_true_on_success(self):
        mock_api = MagicMock()
        mock_api.__enter__ = lambda s: mock_api
        mock_api.__exit__ = MagicMock(return_value=False)

        with patch('tracking.mikrotik_api.router_connection') as mock_conn, \
             patch('tracking.mikrotik_api.get_active_clients', return_value=[{}, {}]):
            mock_conn.return_value.__enter__ = MagicMock(return_value=mock_api)
            mock_conn.return_value.__exit__ = MagicMock(return_value=False)

            from tracking.mikrotik_api import test_router_connection
            result = test_router_connection(self.router)

        self.assertTrue(result['ok'])
        self.assertEqual(result['clients_count'], 2)

    def test_returns_ok_false_on_connection_error(self):
        with patch('tracking.mikrotik_api.router_connection',
                   side_effect=ConnectionError("Injoignable")):
            from tracking.mikrotik_api import test_router_connection
            result = test_router_connection(self.router)

        self.assertFalse(result['ok'])
        self.assertIn('error', result)

    def test_returns_ok_false_on_permission_error(self):
        with patch('tracking.mikrotik_api.router_connection',
                   side_effect=PermissionError("Identifiants refusés")):
            from tracking.mikrotik_api import test_router_connection
            result = test_router_connection(self.router)

        self.assertFalse(result['ok'])
        self.assertIn('Identifiants', result['error'])


# ============================================================
# 5. CELERY TASKS
# ============================================================

@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
class CeleryTasksTest(TestCase):

    def setUp(self):
        self.owner = make_owner()
        self.client_obj = make_client(self.owner)

    def test_close_stale_task_closes_old_sessions(self):
        s = ConnectionSession.objects.create(
            owner=self.owner, client=self.client_obj,
            mac_address='AA:BB:CC:DD:EE:FF',
        )
        ConnectionSession.objects.filter(pk=s.pk).update(
            last_heartbeat=timezone.now() - timedelta(minutes=20)
        )
        close_stale_task.apply()
        s.refresh_from_db()
        self.assertFalse(s.is_active)

    @patch('tracking.tasks.sync_router')
    def test_sync_all_routers_calls_sync_per_router(self, mock_sync):
        """sync_all_mikrotik_routers doit appeler sync_router pour chaque routeur actif."""
        mock_sync.return_value = {'updated': 1, 'created': 0, 'closed': 0}
        make_router(self.owner)
        make_router(self.owner, host='10.0.0.2')

        sync_all_mikrotik_routers.apply()
        self.assertEqual(mock_sync.call_count, 2)

    @patch('tracking.tasks.sync_router', side_effect=Exception("boom"))
    def test_sync_all_routers_survives_one_failure(self, mock_sync):
        """Un routeur défaillant ne doit pas bloquer les autres."""
        make_router(self.owner)
        make_router(self.owner, host='10.0.0.2')

        # Ne doit pas lever d'exception
        try:
            sync_all_mikrotik_routers.apply()
        except Exception:
            self.fail("sync_all_mikrotik_routers ne doit pas propager les exceptions")

    def test_sync_all_routers_skips_inactive_routers(self):
        r = make_router(self.owner)
        r.is_active = False
        r.save()

        with patch('tracking.tasks.sync_router') as mock_sync:
            sync_all_mikrotik_routers.apply()
            mock_sync.assert_not_called()


# ============================================================
# 6. ENDPOINTS PUBLICS — /tracking/heartbeat & /tracking/end
# ============================================================

class TrackingPublicEndpointsTest(APITestCase):

    def setUp(self):
        self.owner = make_owner()
        self.client_obj = make_client(self.owner)
        self.public_key = get_public_key(self.owner)
        self.heartbeat_url = '/api/v1/tracking/heartbeat/'
        self.end_url = '/api/v1/tracking/end/'

    def _base_payload(self, **overrides):
        base = {
            'public_key': str(self.public_key),
            'mac_address': 'AA:BB:CC:DD:EE:FF',
            'uptime': '1m',
            'session_timeout': '4h',
            'bytes_in': '100',
            'bytes_out': '50',
        }
        base.update(overrides)
        return base

    def test_heartbeat_creates_session(self):
        r = self.client.post(
            self.heartbeat_url, self._base_payload(),
            format='json', HTTP_USER_AGENT='Mozilla/5.0 (TestPhone)',
        )
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        self.assertTrue(r.data['ok'])
        self.assertTrue(r.data['created'])
        self.assertIn('session_key', r.data)
        s = ConnectionSession.objects.get(session_key=r.data['session_key'])
        self.assertEqual(s.user_agent, 'Mozilla/5.0 (TestPhone)')

    def test_heartbeat_captures_session_timeout(self):
        """session_timeout_seconds doit être stocké à la création."""
        r = self.client.post(
            self.heartbeat_url,
            self._base_payload(session_timeout='12h'),
            format='json',
        )
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        s = ConnectionSession.objects.get(session_key=r.data['session_key'])
        self.assertEqual(s.session_timeout_seconds, 43200)

    def test_heartbeat_user_agent_truncated(self):
        long_ua = 'A' * 1000
        r = self.client.post(
            self.heartbeat_url, self._base_payload(),
            format='json', HTTP_USER_AGENT=long_ua,
        )
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        s = ConnectionSession.objects.get(session_key=r.data['session_key'])
        self.assertEqual(len(s.user_agent), 512)

    def test_heartbeat_updates_existing(self):
        r1 = self.client.post(self.heartbeat_url, self._base_payload(), format='json')
        sk = r1.data['session_key']
        r2 = self.client.post(self.heartbeat_url, self._base_payload(
            session_key=sk, uptime='2m',
        ), format='json')
        self.assertEqual(r2.status_code, status.HTTP_200_OK)
        self.assertFalse(r2.data['created'])
        self.assertEqual(r2.data['session_key'], sk)

    def test_heartbeat_invalid_mac(self):
        r = self.client.post(self.heartbeat_url, self._base_payload(
            mac_address='not-a-mac',
        ), format='json')
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_heartbeat_missing_public_key(self):
        r = self.client.post(self.heartbeat_url, {
            'mac_address': 'AA:BB:CC:DD:EE:FF',
        }, format='json')
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_heartbeat_unknown_public_key(self):
        r = self.client.post(self.heartbeat_url, self._base_payload(
            public_key=str(uuid.uuid4()),
        ), format='json')
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_heartbeat_unknown_client(self):
        r = self.client.post(self.heartbeat_url, self._base_payload(
            mac_address='11:22:33:44:55:66',
        ), format='json')
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('Client', r.data['detail'])

    def test_end_session(self):
        r = self.client.post(self.heartbeat_url, self._base_payload(), format='json')
        sk = r.data['session_key']
        r2 = self.client.post(self.end_url, {'session_key': sk}, format='json')
        self.assertEqual(r2.status_code, status.HTTP_200_OK)
        self.assertEqual(r2.data['closed'], 1)
        s = ConnectionSession.objects.get(session_key=sk)
        self.assertFalse(s.is_active)

    def test_end_session_invalid_uuid(self):
        r = self.client.post(self.end_url, {'session_key': 'not-a-uuid'}, format='json')
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_end_session_no_auth_required(self):
        r = self.client.post(self.end_url, {'session_key': str(uuid.uuid4())}, format='json')
        self.assertEqual(r.status_code, status.HTTP_200_OK)


# ============================================================
# 7. ENDPOINTS DASHBOARD — /ticket-plans
# ============================================================

class TicketPlanAPITest(APITestCase):

    def setUp(self):
        self.owner = make_owner('owner1@example.com')
        self.other = make_owner('owner2@example.com')
        self.client.force_authenticate(self.owner)
        self.url = '/api/v1/ticket-plans/'

    def test_list_only_own_plans(self):
        TicketPlan.objects.create(owner=self.owner, name='Mine', price_fcfa=100, duration_minutes=60)
        TicketPlan.objects.create(owner=self.other, name='Theirs', price_fcfa=100, duration_minutes=60)
        r = self.client.get(self.url)
        self.assertEqual(r.status_code, 200)
        names = [p['name'] for p in r.data]
        self.assertIn('Mine', names)
        self.assertNotIn('Theirs', names)

    def test_create_assigns_owner(self):
        """v2.0 : plus de download_limit_mb / upload_limit_mb."""
        r = self.client.post(self.url, {
            'name': 'Pass 4h', 'price_fcfa': 200, 'duration_minutes': 240,
        }, format='json')
        self.assertEqual(r.status_code, 201)
        plan = TicketPlan.objects.get(name='Pass 4h')
        self.assertEqual(plan.owner, self.owner)
        self.assertEqual(plan.duration_minutes, 240)

    def test_response_has_no_limit_fields(self):
        """Les champs download/upload_limit_mb ne doivent plus apparaître."""
        r = self.client.post(self.url, {
            'name': 'Pass 1h', 'price_fcfa': 100, 'duration_minutes': 60,
        }, format='json')
        self.assertNotIn('download_limit_mb', r.data)
        self.assertNotIn('upload_limit_mb', r.data)

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
        plan = TicketPlan.objects.create(owner=self.owner, name='Old', price_fcfa=100, duration_minutes=60)
        r = self.client.patch(f'{self.url}{plan.id}/', {'name': 'New'}, format='json')
        self.assertEqual(r.status_code, 200)
        plan.refresh_from_db()
        self.assertEqual(plan.name, 'New')

    def test_cannot_access_others_plan(self):
        plan = TicketPlan.objects.create(owner=self.other, name='Theirs', price_fcfa=100, duration_minutes=60)
        r = self.client.get(f'{self.url}{plan.id}/')
        self.assertEqual(r.status_code, 404)

    def test_delete_own_plan(self):
        plan = TicketPlan.objects.create(owner=self.owner, name='X', price_fcfa=100, duration_minutes=60)
        r = self.client.delete(f'{self.url}{plan.id}/')
        self.assertEqual(r.status_code, 204)
        self.assertFalse(TicketPlan.objects.filter(pk=plan.pk).exists())

    def test_unauthenticated_rejected(self):
        self.client.force_authenticate(None)
        r = self.client.get(self.url)
        self.assertEqual(r.status_code, 401)


# ============================================================
# 8. ENDPOINTS DASHBOARD — /routers (nouveau v2.0)
# ============================================================

class MikroTikRouterAPITest(APITestCase):

    def setUp(self):
        self.owner = make_owner('owner1@example.com')
        self.other = make_owner('owner2@example.com')
        self.client.force_authenticate(self.owner)
        self.url = '/api/v1/routers/'

    def test_create_router(self):
        r = self.client.post(self.url, {
            'name': 'Boutique', 'host': '192.168.88.1',
            'port': 8728, 'username': 'api-user', 'password': 'secret',
        }, format='json')
        self.assertEqual(r.status_code, 201)
        self.assertEqual(MikroTikRouter.objects.filter(owner=self.owner).count(), 1)

    def test_password_not_in_response(self):
        """Le mot de passe ne doit jamais apparaître dans les réponses."""
        r = self.client.post(self.url, {
            'name': 'Test', 'host': '192.168.1.1',
            'port': 8728, 'username': 'admin', 'password': 'secret',
        }, format='json')
        self.assertNotIn('password', r.data)

    def test_list_only_own_routers(self):
        make_router(self.owner, host='10.0.0.1')
        make_router(self.other, host='10.0.0.2')
        r = self.client.get(self.url)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.data), 1)
        self.assertEqual(r.data[0]['host'], '10.0.0.1')

    def test_is_healthy_false_when_no_sync(self):
        make_router(self.owner)
        r = self.client.get(self.url)
        self.assertFalse(r.data[0]['is_healthy'])

    def test_is_healthy_true_after_sync(self):
        router = make_router(self.owner)
        MikroTikRouter.objects.filter(pk=router.pk).update(
            last_synced_at=timezone.now(), last_error='',
        )
        r = self.client.get(self.url)
        self.assertTrue(r.data[0]['is_healthy'])

    def test_update_without_password_keeps_existing(self):
        router = make_router(self.owner, password='original')
        self.client.patch(f'{self.url}{router.id}/', {'name': 'Nouveau nom'}, format='json')
        router.refresh_from_db()
        self.assertEqual(router.get_password(), 'original')

    def test_update_with_new_password(self):
        router = make_router(self.owner, password='ancien')
        self.client.patch(f'{self.url}{router.id}/', {
            'password': 'nouveau',
        }, format='json')
        router.refresh_from_db()
        self.assertEqual(router.get_password(), 'nouveau')

    def test_cannot_access_others_router(self):
        router = make_router(self.other)
        r = self.client.get(f'{self.url}{router.id}/')
        self.assertEqual(r.status_code, 404)

    def test_delete_router(self):
        router = make_router(self.owner)
        r = self.client.delete(f'{self.url}{router.id}/')
        self.assertEqual(r.status_code, 204)
        self.assertFalse(MikroTikRouter.objects.filter(pk=router.pk).exists())

    def test_unauthenticated_rejected(self):
        self.client.force_authenticate(None)
        r = self.client.get(self.url)
        self.assertEqual(r.status_code, 401)

    @patch('tracking.views.test_router_connection')
    def test_test_connection_success(self, mock_test):
        mock_test.return_value = {'ok': True, 'clients_count': 3}
        router = make_router(self.owner)
        r = self.client.post(f'{self.url}{router.id}/test-connection/')
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.data['ok'])
        self.assertEqual(r.data['clients_count'], 3)

    @patch('tracking.views.test_router_connection')
    def test_test_connection_failure_returns_502(self, mock_test):
        mock_test.return_value = {'ok': False, 'error': "Injoignable"}
        router = make_router(self.owner)
        r = self.client.post(f'{self.url}{router.id}/test-connection/')
        self.assertEqual(r.status_code, 502)
        self.assertFalse(r.data['ok'])
        self.assertIn('error', r.data)

    @patch('tracking.views.sync_router')
    def test_sync_now(self, mock_sync):
        mock_sync.return_value = {'updated': 4, 'created': 0, 'closed': 1}
        router = make_router(self.owner)
        r = self.client.post(f'{self.url}{router.id}/sync-now/')
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.data['ok'])
        self.assertEqual(r.data['updated'], 4)
        self.assertEqual(r.data['closed'], 1)


# ============================================================
# 9. ENDPOINTS DASHBOARD — /sessions
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
        self.assertEqual(len(r.data), 1)

    def test_filter_active(self):
        self._session(self.owner, self.client_obj, is_active=True)
        self._session(self.owner, self.client_obj, is_active=False)
        r = self.client.get(self.url, {'is_active': 'true'})
        self.assertEqual(len(r.data), 1)
        self.assertTrue(r.data[0]['is_active'])

    def test_filter_by_client(self):
        s = self._session(self.owner, self.client_obj)
        other_c = make_client(self.owner, mac='99:88:77:66:55:44', email='b@x.com')
        self._session(self.owner, other_c)
        r = self.client.get(self.url, {'client': self.client_obj.id})
        self.assertEqual(len(r.data), 1)
        self.assertEqual(r.data[0]['id'], s.id)

    def test_retrieve_includes_new_fields(self):
        """v2.0 : router_name et session_timeout_seconds dans la réponse."""
        router = make_router(self.owner)
        s = self._session(
            self.owner, self.client_obj,
            uptime_seconds=180,
            session_timeout_seconds=14400,
            router=router,
        )
        r = self.client.get(f'{self.url}{s.id}/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data['duration_seconds'], 180)
        self.assertEqual(r.data['session_timeout_seconds'], 14400)
        self.assertEqual(r.data['router_name'], router.name)

    def test_router_name_null_when_no_router(self):
        s = self._session(self.owner, self.client_obj)
        r = self.client.get(f'{self.url}{s.id}/')
        self.assertIsNone(r.data['router_name'])

    def test_unauthenticated_rejected(self):
        self.client.force_authenticate(None)
        r = self.client.get(self.url)
        self.assertEqual(r.status_code, 401)


# ============================================================
# 10. ENDPOINTS DASHBOARD — /session-analytics
# ============================================================

class SessionAnalyticsAPITest(APITestCase):

    def setUp(self):
        self.owner = make_owner('a@x.com')
        self.other = make_owner('b@x.com')
        self.client_obj = make_client(self.owner)
        self.client.force_authenticate(self.owner)
        self.plan = TicketPlan.objects.create(
            owner=self.owner, name='Pass 1h', price_fcfa=200, duration_minutes=60,
        )

    def _session(self, owner=None, **kwargs):
        owner = owner or self.owner
        return ConnectionSession.objects.create(
            owner=owner,
            client=self.client_obj if owner == self.owner
                   else make_client(owner, mac='AA:11:22:33:44:55', email='z@x.com'),
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
        ConnectionSession.objects.create(owner=self.other, client=oc, mac_address=oc.mac_address)
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
