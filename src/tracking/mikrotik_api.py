# tracking/mikrotik_api.py
"""
Couche d'accès à l'API RouterOS MikroTik.

Responsabilités :
- Connexion au routeur via librouteros
- Récupération des clients hotspot actifs
- Synchronisation avec les sessions en base
"""
import logging
from contextlib import contextmanager
from django.utils import timezone

import librouteros
from librouteros.exceptions import TrapError, ConnectionClosed, LibRouterosError
# On utilise le ConnectionError standard de Python comme alias si besoin
MKConnectionError = (ConnectionClosed, LibRouterosError, ConnectionError)

from .models import (
    MikroTikRouter,
    ConnectionSession,
    parse_mikrotik_uptime,
)

logger = logging.getLogger(__name__)


# ----------------------------------------------------------------
# Connexion
# ----------------------------------------------------------------

@contextmanager
def router_connection(router: MikroTikRouter):
    """
    Gestionnaire de contexte pour se connecter à un routeur MikroTik.
    Ferme proprement la connexion à la sortie, même en cas d'erreur.

    Usage :
        with router_connection(router) as api:
            clients = api('/ip/hotspot/active/print')
    """
    api = None
    try:
        api = librouteros.connect(
            host=router.host,
            username=router.username,
            password=router.get_password(),
            port=router.port,
            timeout=10,  # secondes — on ne veut pas bloquer Celery trop longtemps
        )
        yield api
    except MKConnectionError as e:
        raise ConnectionError(f"Impossible de joindre {router.host}:{router.port} — {e}")
    except TrapError as e:
        raise PermissionError(f"Identifiants refusés par {router.host} — {e}")
    finally:
        if api:
            try:
                api.close()
            except Exception:
                pass


def test_router_connection(router: MikroTikRouter) -> dict:
    """
    Teste la connexion à un routeur et retourne un résultat structuré.
    Utilisé lors de la sauvegarde depuis le dashboard owner.

    Returns:
        {'ok': True, 'clients_count': 5}
        {'ok': False, 'error': "message d'erreur lisible"}
    """
    try:
        with router_connection(router) as api:
            clients = list(api('/ip/hotspot/active/print'))
            return {'ok': True, 'clients_count': len(clients)}
    except ConnectionError as e:
        return {'ok': False, 'error': str(e)}
    except PermissionError as e:
        return {'ok': False, 'error': str(e)}
    except Exception as e:
        return {'ok': False, 'error': f"Erreur inattendue : {e}"}


# ----------------------------------------------------------------
# Récupération des clients actifs
# ----------------------------------------------------------------

def get_active_clients(api) -> list[dict]:
    """
    Récupère et normalise la liste des clients hotspot actifs.

    MikroTik retourne des champs comme 'bytes-in', 'mac-address', etc.
    On normalise les clés en snake_case et on convertit les valeurs utiles.

    Returns:
        Liste de dicts avec les clés normalisées :
        {
            'mac_address': 'AA:BB:CC:DD:EE:FF',
            'username': 'ABC123',
            'ip_address': '192.168.1.10',
            'uptime_seconds': 5025,
            'session_timeout_seconds': 14400,
            'bytes_downloaded': 15234567,
            'bytes_uploaded': 8765432,
            'session_id': '...',
        }
    """
    raw_clients = list(api('/ip/hotspot/active/print'))
    normalized = []

    for c in raw_clients:
        try:
            normalized.append({
                'mac_address':             c.get('mac-address', '').upper(),
                'username':                c.get('user', ''),
                'ip_address':              c.get('address') or None,
                'uptime_seconds':          parse_mikrotik_uptime(c.get('uptime', '')),
                # session-timeout = durée totale accordée au ticket
                'session_timeout_seconds': parse_mikrotik_uptime(
                    c.get('session-timeout', '')
                ),
                'bytes_downloaded':        int(c.get('bytes-in', 0) or 0),
                'bytes_uploaded':          int(c.get('bytes-out', 0) or 0),
                'session_id':              c.get('session-id') or None,
            })
        except Exception as e:
            logger.warning("[mikrotik_api] Erreur normalisation client %s : %s", c, e)

    return normalized


# ----------------------------------------------------------------
# Synchronisation sessions ↔ MikroTik
# ----------------------------------------------------------------

def sync_router(router: MikroTikRouter) -> dict:
    """
    Synchronise les sessions en base avec l'état réel du routeur.

    Pour chaque client actif dans MikroTik :
        → Retrouver la session active en base via MAC address
        → Si trouvée : mettre à jour (uptime, bytes, etc.)
        → Si pas trouvée : créer la session (cas où tracker.js a raté)

    Pour chaque session active en base absente de la liste MikroTik :
        → Le client est vraiment déconnecté → fermer la session

    Returns:
        {
            'updated': N,   # sessions mises à jour
            'created': N,   # sessions créées (sans passage par tracker.js)
            'closed': N,    # sessions fermées (clients partis)
        }
    """
    from .services import match_ticket_plan
    from core_data.models import OwnerClient

    stats = {'updated': 0, 'created': 0, 'closed': 0}
    now = timezone.now()

    try:
        with router_connection(router) as api:
            active_clients = get_active_clients(api)
    except (ConnectionError, PermissionError) as e:
        # On note l'erreur sur le routeur et on arrête
        MikroTikRouter.objects.filter(pk=router.pk).update(last_error=str(e))
        logger.error("[sync] Routeur %s inaccessible : %s", router, e)
        return stats
    except Exception as e:
        MikroTikRouter.objects.filter(pk=router.pk).update(last_error=str(e))
        logger.exception("[sync] Erreur inattendue routeur %s", router)
        return stats

    # MACs actuellement actives sur MikroTik
    active_macs = {c['mac_address'] for c in active_clients}

    # Sessions actives en base pour ce routeur/owner
    sessions_in_db = {
        s.mac_address: s
        for s in ConnectionSession.objects.filter(
            owner=router.owner,
            is_active=True,
        ).select_related('ticket_plan')
    }

    # --- Mise à jour et création ---
    for client in active_clients:
        mac = client['mac_address']
        if not mac:
            continue

        if mac in sessions_in_db:
            # Client connu → mise à jour
            session = sessions_in_db[mac]
            session.uptime_seconds   = client['uptime_seconds']
            session.bytes_downloaded = client['bytes_downloaded']
            session.bytes_uploaded   = client['bytes_uploaded']
            session.ip_address       = client['ip_address'] or session.ip_address
            session.router           = router
            session.save(update_fields=[
                'uptime_seconds', 'bytes_downloaded', 'bytes_uploaded',
                'ip_address', 'router', 'last_heartbeat',
            ])
            stats['updated'] += 1

        else:
            # Client inconnu → créer la session directement depuis MikroTik
            # (tracker.js n'a pas pu envoyer le 1er heartbeat)
            try:
                owner_client = OwnerClient.objects.get(
                    owner=router.owner,
                    mac_address=mac,
                )
            except OwnerClient.DoesNotExist:
                # Client pas encore enregistré — on l'ignore pour cette synchro
                logger.info("[sync] MAC %s inconnue pour owner %s", mac, router.owner)
                continue

            session_timeout = client['session_timeout_seconds']
            plan = match_ticket_plan(
                owner=router.owner,
                session_timeout_seconds=session_timeout,
            )
            ConnectionSession.objects.create(
                owner=router.owner,
                client=owner_client,
                router=router,
                mac_address=mac,
                ip_address=client['ip_address'],
                ticket_id=client['username'] or None,
                mikrotik_session_id=client['session_id'],
                session_timeout_seconds=session_timeout,
                uptime_seconds=client['uptime_seconds'],
                bytes_downloaded=client['bytes_downloaded'],
                bytes_uploaded=client['bytes_uploaded'],
                ticket_plan=plan,
                is_active=True,
            )
            stats['created'] += 1
            logger.info("[sync] Session créée depuis MikroTik pour MAC %s", mac)

    # --- Fermeture des sessions dont le client est parti ---
    for mac, session in sessions_in_db.items():
        if mac not in active_macs:
            session.is_active = False
            session.ended_at  = now
            session.save(update_fields=['is_active', 'ended_at'])
            stats['closed'] += 1
            logger.info("[sync] Session fermée pour MAC %s (absent de MikroTik)", mac)

    # Mise à jour last_synced_at et effacement de last_error
    MikroTikRouter.objects.filter(pk=router.pk).update(
        last_synced_at=now,
        last_error='',
    )

    logger.info(
        "[sync] Routeur %s — màj=%d créé=%d fermé=%d",
        router, stats['updated'], stats['created'], stats['closed'],
    )
    return stats
