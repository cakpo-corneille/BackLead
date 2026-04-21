# tracking/services.py
import logging
from django.utils import timezone
from core_data.models import FormSchema, OwnerClient
from .models import (
    ConnectionSession,
    TicketPlan,
    parse_mikrotik_uptime,
    parse_mikrotik_limit,
)

logger = logging.getLogger(__name__)


def handle_heartbeat(data):
    """
    Point d'entrée unique pour un heartbeat tracker.
    Crée la session si elle n'existe pas, la met à jour sinon.

    Args:
        data (dict): données validées par HeartbeatSerializer.

    Returns:
        (session: ConnectionSession, created: bool)

    Raises:
        ValueError: public_key inconnue ou client introuvable.
    """
    session_key = data.get('session_key')

    # --- Mise à jour d'une session existante ---
    if session_key:
        try:
            session = (
                ConnectionSession.objects
                .select_related('owner', 'client', 'ticket_plan')
                .get(session_key=session_key)
            )
            _apply_heartbeat(session, data)
            return session, False
        except ConnectionSession.DoesNotExist:
            logger.warning(
                "[tracking] session_key inconnue %s → création d'une nouvelle session",
                session_key,
            )

    # --- Résolution de l'owner via public_key ---
    try:
        schema = FormSchema.objects.select_related('owner').get(
            public_key=data['public_key']
        )
        owner = schema.owner
    except FormSchema.DoesNotExist:
        raise ValueError(f"public_key invalide : {data.get('public_key')}")

    # --- Résolution du client (obligatoire — ordre inviolable widget → tracker) ---
    mac = data['mac_address'].upper()
    try:
        client = OwnerClient.objects.get(owner=owner, mac_address=mac)
    except OwnerClient.DoesNotExist:
        raise ValueError(f"Client non trouvé pour MAC : {mac}")

    # --- Création de la session ---
    download_limit = parse_mikrotik_limit(data.get('rx_limit'))
    upload_limit = parse_mikrotik_limit(data.get('tx_limit'))

    session = ConnectionSession.objects.create(
        owner=owner,
        client=client,
        mac_address=mac,
        ip_address=data.get('ip_address') or None,
        ticket_id=data.get('username') or None,
        mikrotik_session_id=data.get('session_id') or None,
        download_limit_bytes=download_limit,
        upload_limit_bytes=upload_limit,
    )
    _apply_heartbeat(session, data)

    # Matching plan tarifaire (best-effort, non bloquant)
    plan = match_ticket_plan(
        owner=owner,
        download_limit_bytes=download_limit,
        upload_limit_bytes=upload_limit,
        uptime_seconds=session.uptime_seconds,
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
    """Applique les données fraîches d'un heartbeat MikroTik."""
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
    # JSONField n'accepte pas les UUID/datetime issus de la validation DRF :
    # on stringifie tout ce qui n'est pas natif JSON.
    session.last_raw_data = {
        k: (str(v) if not isinstance(v, (str, int, float, bool, type(None))) else v)
        for k, v in data.items()
    }
    session.save()


def match_ticket_plan(owner, download_limit_bytes, upload_limit_bytes, uptime_seconds):
    """
    Identifie le TicketPlan correspondant à une session.

    Stratégie :
    1. Si rx-limit/tx-limit présents → match par limites de bytes (égalité stricte).
    2. Sinon (limites illimitées) → fallback par durée la plus proche
       parmi les plans actifs de l'owner.

    Returns:
        TicketPlan | None
    """
    plans = TicketPlan.objects.filter(owner=owner, is_active=True)

    if download_limit_bytes is not None or upload_limit_bytes is not None:
        for plan in plans:
            if (
                plan.download_limit_bytes == download_limit_bytes
                and plan.upload_limit_bytes == upload_limit_bytes
            ):
                return plan
        return None

    # Fallback durée : plan dont duration_minutes * 60 est le plus proche de uptime_seconds
    if uptime_seconds <= 0:
        return None
    best = None
    best_diff = None
    for plan in plans:
        diff = abs(plan.duration_minutes * 60 - uptime_seconds)
        if best_diff is None or diff < best_diff:
            best = plan
            best_diff = diff
    return best


def close_session(session_key):
    """Ferme une session (déclenchée par logout.html ou Celery)."""
    return ConnectionSession.objects.filter(
        session_key=session_key,
        is_active=True,
    ).update(is_active=False, ended_at=timezone.now())


def close_stale_sessions(threshold_minutes=10):
    """
    Marque comme terminées les sessions sans heartbeat depuis N minutes.
    MikroTik refresh typiquement toutes les ~60s.
    10 minutes sans heartbeat = client déconnecté sans passer par logout.

    L'heure de fin approximative est last_heartbeat (date du dernier signal reçu).
    """
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
