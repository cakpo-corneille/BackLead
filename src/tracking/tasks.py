# tracking/tasks.py
"""
Tâche Celery pour le tracking WiFi.

close_expired_sessions : tourne toutes les 5 minutes.
Ferme les sessions actives dont la durée théorique est dépassée
et pour lesquelles on-logout n'est jamais arrivé (coupure courant,
crash routeur, perte réseau).

Les scripts MikroTik on-login / on-logout gèrent le flux normal.
Celery est uniquement le filet de sécurité.
"""
import logging
from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(
    bind=True,
    max_retries=0,
    ignore_result=True,
    name='tracking.close_expired_sessions',
)
def close_expired_sessions(self):
    """
    Ferme les sessions dont la durée théorique est dépassée depuis
    plus de 10 minutes (on-logout jamais reçu).
    Planifié toutes les 5 minutes dans CELERY_BEAT_SCHEDULE.
    """
    from .hotspot_service import close_expired_sessions as _close
    count = _close()
    if count:
        logger.info("[task] %d sessions expirées fermées par le serveur", count)
