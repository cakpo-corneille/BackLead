# tracking/hotspot_service.py
"""
Logique métier pour les événements hotspot MikroTik.

Deux chemins d'entrée :
  - on-login  → handle_login()
  - on-logout → handle_logout()

Filet de sécurité :
  - close_expired_sessions() → appelée par Celery Beat toutes les 5 min
"""
import logging
from django.utils import timezone
from core_data.models import FormSchema, OwnerClient
from .models import ConnectionSession, parse_mikrotik_uptime
from .services import match_ticket_plan

logger = logging.getLogger(__name__)


# ----------------------------------------------------------------
# Authentification routeur → backend
# ----------------------------------------------------------------

def validate_owner_key(owner_key):
    """
    Identifie l'owner via la public_key de son FormSchema.
    Lève ValueError si la clé est inconnue.
    """
    try:
        schema = FormSchema.objects.select_related('owner').get(
            public_key=owner_key
        )
        return schema.owner
    except FormSchema.DoesNotExist:
        raise ValueError(f"owner_key invalide : {owner_key}")


# ----------------------------------------------------------------
# on-login
# ----------------------------------------------------------------

def handle_login(owner, data):
    """
    Crée une ConnectionSession à partir des données du script on-login.

    data attendu (déjà validé par HotspotLoginSerializer) :
        mac, ip, user, session_id, uptime_limit, owner_key
        + optionnel : server, interface

    Retourne la session créée.
    """
    mac = data['mac'].upper().replace('-', ':')

    # Le client doit exister — il doit avoir rempli le formulaire du portail captif.
    # Le tracking ne crée pas de clients à la volée.
    try:
        client = OwnerClient.objects.get(owner=owner, mac_address=mac)
    except OwnerClient.DoesNotExist:
        logger.info(
            "[hotspot] LOGIN ignoré — client inconnu MAC=%s owner=%s",
            mac, owner.email,
        )
        return None

    client.last_seen = timezone.now()
    client.save(update_fields=['last_seen'])

    # Durée du ticket → identification du plan tarifaire
    session_timeout_seconds = parse_mikrotik_uptime(data.get('uptime_limit', ''))

    session = ConnectionSession.objects.create(
        owner=owner,
        client=client,
        mac_address=mac,
        ip_address=data.get('ip') or None,
        ticket_id=data.get('user') or None,
        mikrotik_session_id=data.get('session_id') or None,
        session_timeout_seconds=session_timeout_seconds,
        is_active=True,
    )

    # Matching plan tarifaire par durée
    plan = match_ticket_plan(
        owner=owner,
        session_timeout_seconds=session_timeout_seconds,
    )
    if plan:
        session.ticket_plan = plan
        session.amount_fcfa = plan.price_fcfa
        session.save(update_fields=['ticket_plan', 'amount_fcfa'])

    logger.info(
        "[hotspot] LOGIN  session=%s MAC=%s plan=%s timeout=%ds",
        session.session_key, mac,
        plan.name if plan else "—",
        session_timeout_seconds,
    )
    return session


# ----------------------------------------------------------------
# on-logout
# ----------------------------------------------------------------

def handle_logout(owner, data):
    """
    Ferme une ConnectionSession à partir des données du script on-logout.

    data attendu (déjà validé par HotspotLogoutSerializer) :
        mac, session_id, uptime, bytes_in, bytes_out, cause, owner_key

    Retourne la session mise à jour, ou None si introuvable.
    """
    session_id = data.get('session_id', '')

    try:
        session = ConnectionSession.objects.select_related('owner').get(
            mikrotik_session_id=session_id,
            owner=owner,
        )
    except ConnectionSession.DoesNotExist:
        logger.warning(
            "[hotspot] LOGOUT session_id=%s introuvable (owner=%s)",
            session_id, owner,
        )
        return None

    if not session.is_active:
        # Déjà fermée (double signal ou Celery plus rapide)
        return session

    session.uptime_seconds = parse_mikrotik_uptime(data.get('uptime', ''))
    try:
        session.bytes_downloaded = int(data.get('bytes_in') or 0)
    except (TypeError, ValueError):
        session.bytes_downloaded = 0
    try:
        session.bytes_uploaded = int(data.get('bytes_out') or 0)
    except (TypeError, ValueError):
        session.bytes_uploaded = 0

    session.disconnect_cause = (data.get('cause') or '')[:64]
    session.is_active = False
    session.ended_at = timezone.now()

    session.save(update_fields=[
        'uptime_seconds', 'bytes_downloaded', 'bytes_uploaded',
        'disconnect_cause', 'is_active', 'ended_at',
    ])

    if session.client is not None:
        session.client.last_seen = timezone.now()
        session.client.save(update_fields=['last_seen'])

    logger.info(
        "[hotspot] LOGOUT session=%s MAC=%s cause=%s uptime=%ds",
        session.session_key, session.mac_address,
        session.disconnect_cause, session.uptime_seconds,
    )
    return session


# ----------------------------------------------------------------
# Filet de sécurité Celery
# ----------------------------------------------------------------

def close_expired_sessions():
    """
    Ferme les sessions actives dont la durée théorique est dépassée
    depuis plus de 10 minutes (marge de sécurité).

    Cas couverts :
      - routeur crash sans envoyer on-logout
      - connexion réseau coupée entre le routeur et le backend

    Appelée par Celery Beat toutes les 10 minutes.
    Compatible SQLite (tests) et PostgreSQL (prod).
    """
    from datetime import timedelta

    now = timezone.now()
    grace = timedelta(minutes=10)

    # Calcul de l'expiration en Python sur les IDs uniquement (pas de chargement complet)
    candidates = ConnectionSession.objects.filter(
        is_active=True,
        session_timeout_seconds__gt=0,
    ).values('id', 'started_at', 'session_timeout_seconds')

    expired_ids = []
    for row in candidates:
        theoretical_end = (
            row['started_at']
            + timedelta(seconds=row['session_timeout_seconds'])
            + grace
        )
        if now >= theoretical_end:
            expired_ids.append(row['id'])

    if not expired_ids:
        return 0

    # UPDATE groupé en une seule requête SQL
    count = ConnectionSession.objects.filter(id__in=expired_ids).update(
        is_active=False,
        ended_at=now,
        disconnect_cause='expired-by-server',
    )

    if count:
        logger.info("[hotspot] %d sessions expirées fermées par le serveur", count)

    return count
