# tracking/tasks.py
"""
Tâches Celery pour le tracking WiFi.

- sync_all_mikrotik_routers : tourne toutes les 2 minutes,
  interroge chaque routeur actif et met à jour les sessions.
- close_stale_sessions     : filet de sécurité, toutes les 10 min.
"""
import logging
from celery import shared_task
from .models import MikroTikRouter

logger = logging.getLogger(__name__)


@shared_task(
    bind=True,
    max_retries=0,       # pas de retry : la prochaine exécution arrive dans 2 min
    ignore_result=True,
    name='tracking.sync_all_mikrotik_routers',
)
def sync_all_mikrotik_routers(self):
    """
    Interroge tous les routeurs MikroTik actifs et synchronise les sessions.
    À planifier toutes les 2 minutes dans CELERY_BEAT_SCHEDULE.
    """
    from .mikrotik_api import sync_router

    routers = MikroTikRouter.objects.filter(is_active=True).select_related('owner')

    if not routers.exists():
        return

    total = {'updated': 0, 'created': 0, 'closed': 0}

    for router in routers:
        try:
            stats = sync_router(router)
            for key in total:
                total[key] += stats.get(key, 0)
        except Exception as e:
            # On ne laisse pas un routeur planter toute la tâche
            logger.exception("[task] Erreur synchro routeur %s : %s", router, e)

    logger.info(
        "[task] Synchro terminée — màj=%d créé=%d fermé=%d",
        total['updated'], total['created'], total['closed'],
    )


@shared_task(
    bind=True,
    max_retries=0,
    ignore_result=True,
    name='tracking.close_stale_sessions',
)
def close_stale_sessions(self):
    """
    Filet de sécurité : ferme les sessions sans heartbeat depuis 10 min.
    Utile si un routeur est hors ligne et que la synchro échoue.
    À planifier toutes les 10 minutes dans CELERY_BEAT_SCHEDULE.
    """
    from .services import close_stale_sessions as _close
    count = _close(threshold_minutes=10)
    if count:
        logger.info("[task] %d sessions périmées fermées", count)
