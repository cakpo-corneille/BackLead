# tracking/services.py
import logging
from django.utils import timezone
from core_data.models import FormSchema, OwnerClient
from .models import (
    ConnectionSession,
    TicketPlan,
    parse_mikrotik_uptime,
)

logger = logging.getLogger(__name__)


def handle_heartbeat(data, user_agent=''):
    session_key = data.get('session_key')

    if session_key:
        try:
            session = (
                ConnectionSession.objects
                .select_related('owner', 'client', 'ticket_plan')
                .get(session_key=session_key)
            )
            _apply_heartbeat(session, data)
            if user_agent and not session.user_agent:
                session.user_agent = user_agent[:512]
                session.save(update_fields=['user_agent'])
            return session, False
        except ConnectionSession.DoesNotExist:
            logger.warning(
                "[tracking] session_key inconnue %s → création d'une nouvelle session",
                session_key,
            )

    try:
        schema = FormSchema.objects.select_related('owner').get(
            public_key=data['public_key']
        )
        owner = schema.owner
    except FormSchema.DoesNotExist:
        raise ValueError(f"public_key invalide : {data.get('public_key')}")

    mac = data['mac_address'].upper()
    try:
        client = OwnerClient.objects.get(owner=owner, mac_address=mac)
    except OwnerClient.DoesNotExist:
        raise ValueError(f"Client non trouvé pour MAC : {mac}")

    # ✅ On lit session_timeout dès la création
    session_timeout_seconds = parse_mikrotik_uptime(data.get('session_timeout', ''))

    session = ConnectionSession.objects.create(
        owner=owner,
        client=client,
        mac_address=mac,
        ip_address=data.get('ip_address') or None,
        ticket_id=data.get('username') or None,
        mikrotik_session_id=data.get('session_id') or None,
        session_timeout_seconds=session_timeout_seconds,
        user_agent=(user_agent or '')[:512],
    )
    _apply_heartbeat(session, data)

    # ✅ Matching plan uniquement par durée (session_timeout)
    plan = match_ticket_plan(
        owner=owner,
        session_timeout_seconds=session_timeout_seconds,
    )
    if plan:
        session.ticket_plan = plan
        session.save(update_fields=['ticket_plan'])

    logger.info(
        "[tracking] Nouvelle session %s pour %s (plan=%s)",
        session.session_key, mac, plan.name if plan else "—",
    )
    return session, True


def _apply_heartbeat(session, data):
    session.uptime_seconds = parse_mikrotik_uptime(data.get('uptime', ''))
    try:
        session.bytes_downloaded = int(data.get('bytes_in') or 0)
    except (TypeError, ValueError):
        session.bytes_downloaded = 0
    try:
        session.bytes_uploaded = int(data.get('bytes_out') or 0)
    except (TypeError, ValueError):
        session.bytes_uploaded = 0
    session.is_active = True
    session.last_raw_data = {
        k: (str(v) if not isinstance(v, (str, int, float, bool, type(None))) else v)
        for k, v in data.items()
    }
    session.save()


def match_ticket_plan(owner, session_timeout_seconds):
    """
    Identifie le TicketPlan dont la durée correspond à session_timeout.
    On prend le plan dont la durée en secondes est la plus proche.
    Ex: session_timeout = 14400s (4h) → plan 240 min → trouvé.
    """
    if not session_timeout_seconds or session_timeout_seconds <= 0:
        return None

    plans = TicketPlan.objects.filter(owner=owner, is_active=True)
    best = None
    best_diff = None

    for plan in plans:
        diff = abs(plan.duration_minutes * 60 - session_timeout_seconds)
        if best_diff is None or diff < best_diff:
            best = plan
            best_diff = diff

    return best


def close_session(session_key):
    return ConnectionSession.objects.filter(
        session_key=session_key,
        is_active=True,
    ).update(is_active=False, ended_at=timezone.now())


def close_stale_sessions(threshold_minutes=10):
    cutoff = timezone.now() - timezone.timedelta(minutes=threshold_minutes)
    stale = ConnectionSession.objects.filter(
        is_active=True,
        last_heartbeat__lt=cutoff,
    )
    count = 0
    for session in stale:
        session.is_active = False
        session.ended_at = session.last_heartbeat
        session.save(update_fields=['is_active', 'ended_at'])
        count += 1
    return count
