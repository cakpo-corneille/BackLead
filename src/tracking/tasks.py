# tracking/tasks.py
import logging
from celery import shared_task
from .services import close_stale_sessions

logger = logging.getLogger(__name__)


@shared_task(name='tracking.cleanup_stale_sessions')
def cleanup_stale_sessions_task():
    """
    Ferme les sessions sans heartbeat depuis plus de 10 minutes.
    MikroTik refresh toutes les ~60s → 10 min = déconnexion certaine.

    L'heure de fin est positionnée à la date du dernier heartbeat reçu
    (approximation au plus juste).
    """
    count = close_stale_sessions(threshold_minutes=10)
    if count:
        logger.info("[tracking] %d sessions orphelines fermées", count)
    return count
