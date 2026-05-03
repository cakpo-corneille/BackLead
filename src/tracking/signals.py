# tracking/signals.py
"""
Signaux post_save sur ConnectionSession :
  1. Nouveau client détecté → incrémente recognition_level
  2. Session créée ou fermée → invalide le cache analytics de l'owner
"""
import logging
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import ConnectionSession

logger = logging.getLogger(__name__)


@receiver(post_save, sender=ConnectionSession)
def on_connection_session_saved(sender, instance, created, **kwargs):
    # ----------------------------------------------------------------
    # 1. Incrémenter recognition_level du client à chaque nouvelle session
    # ----------------------------------------------------------------
    if created:
        client = instance.client
        if client is not None:
            client.recognition_level = (client.recognition_level or 0) + 1
            client.save(update_fields=['recognition_level'])
            logger.debug(
                "[signal] recognition_level client=%s → %d",
                client.pk, client.recognition_level,
            )

    # ----------------------------------------------------------------
    # 2. Invalider le cache analytics dès qu'une session est créée
    #    ou vient d'être fermée (is_active passé à False)
    # ----------------------------------------------------------------
    session_just_closed = not instance.is_active and not created

    if created or session_just_closed:
        try:
            from core_data.services.dashboard.analytics import invalidate_analytics_cache
            invalidate_analytics_cache(instance.owner_id)
            logger.debug(
                "[signal] cache analytics invalidé pour owner=%s",
                instance.owner_id,
            )
        except Exception:
            logger.exception(
                "[signal] Échec invalidation cache analytics (owner=%s)",
                instance.owner_id,
            )
