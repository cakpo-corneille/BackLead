# tracking/services.py
from django.utils import timezone
from core_data.models import FormSchema, OwnerClient
from .models import ConnectionSession, parse_mikrotik_uptime, parse_mikrotik_limit
import logging

logger = logging.getLogger(__name__)


def handle_heartbeat(data):
    """
    Point d'entrée unique pour un heartbeat tracker.
    Crée la session si elle n'existe pas encore, la met à jour sinon.

    Args:
        data (dict): données issues des data-* attributes, parsées par le serializer

    Returns:
        (session: ConnectionSession, created: bool)
    """
    session_key = data.get('session_key')

    # --- Mise à jour d'une session existante ---
    if session_key:
        try:
            session = ConnectionSession.objects.select_related('owner', 'client').get(
                session_key=session_key
            )
            _apply_heartbeat(session, data)
            return session, False
        except ConnectionSession.DoesNotExist:
            logger.warning(f"[tracking] session_key inconnu {session_key}, création d'une nouvelle session")

    # --- Résolution de l'owner via public_key ---
    try:
        schema = FormSchema.objects.select_related('owner').get(
            public_key=data['public_key']
        )
        owner = schema.owner
    except FormSchema.DoesNotExist:
        raise ValueError(f"public_key invalide : {data.get('public_key')}")
# --- Résolution du client (obligatoire) ---
mac = data['mac_address'].upper()
try:
    client = OwnerClient.objects.get(owner=owner, mac_address=mac)
except OwnerClient.DoesNotExist:
    raise ValueError(f"Client non trouvé pour MAC : {mac}")

# --- Création de la session ---
session = ConnectionSession.objects.create(
    owner=owner,
    client=client,
    mac_address=mac,
...
        ip_address=data.get('ip_address'),
        ticket_id=data.get('username'),
        mikrotik_session_id=data.get('session_id'),
        download_limit_bytes=parse_mikrotik_limit(data.get('rx_limit')),
        upload_limit_bytes=parse_mikrotik_limit(data.get('tx_limit')),
    )
    _apply_heartbeat(session, data)
    logger.info(f"[tracking] Nouvelle session {session.session_key} pour {mac}")
    return session, True


def _apply_heartbeat(session, data):
    """
    Applique les données fraîches d'un heartbeat MikroTik.
    """
    session.uptime_seconds   = parse_mikrotik_uptime(data.get('uptime', ''))
    session.bytes_downloaded = int(data.get('bytes_in') or 0)
    session.bytes_uploaded   = int(data.get('bytes_out') or 0)
    session.is_active        = True
    session.last_raw_data    = data
    session.save()


def close_session(session_key):
    """Ferme une session (déclenchée par logout.html ou Celery)."""
    return ConnectionSession.objects.filter(
        session_key=session_key,
        is_active=True
    ).update(is_active=False, ended_at=timezone.now())


def close_stale_sessions(threshold_minutes=10):
    """
    Marque comme terminées les sessions sans heartbeat depuis N minutes.
    MikroTik refreshe typiquement toutes les 60s.
    10 minutes sans heartbeat = client déconnecté sans passer par logout.
    """
    cutoff = timezone.now() - timezone.timedelta(minutes=threshold_minutes)
    count = ConnectionSession.objects.filter(
        is_active=True,
        last_heartbeat__lt=cutoff
    ).update(is_active=False, ended_at=timezone.now())
    return count
