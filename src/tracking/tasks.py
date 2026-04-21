# tracking/tasks.py
from celery import shared_task
import logging
from .services import close_stale_sessions, reconcile_orphan_sessions

logger = logging.getLogger(__name__)


@shared_task(name='tracking.cleanup_stale_sessions')
def cleanup_stale_sessions_task():
    """
    Ferme les sessions sans heartbeat depuis plus de 10 minutes.
    MikroTik refresh toutes les ~60s → 10 min = déconnexion certaine.
    """
    count = close_stale_sessions(threshold_minutes=10)
    if count:
        logger.info(f"[tracking] {count} sessions orphelines fermées")
    return count


@shared_task(name='tracking.reconcile_sessions')
def reconcile_sessions_task():
    """
    Rattache les sessions sans client (race condition widget/tracker).
    Exécuté fréquemment pour combler la fenêtre de quelques secondes.
    """
    return reconcile_orphan_sessions()
