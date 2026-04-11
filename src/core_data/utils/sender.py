# src/core_data/utils/sender.py

import logging
logger = logging.getLogger(__name__)


def send_code_async_or_sync(client):
    """
    Envoie le code de double opt-in de façon asynchrone si un worker
    Celery est disponible, sinon bascule en synchrone immédiat.
    
    La vérification des workers ajoute ~1s de latence au pire cas,
    ce qui est acceptable pour un envoi de code de vérification.
    """
    from config.celery_utils import has_active_celery_workers
    from ..tasks import send_verification_code_task
    from core_data.services.portal.messages_services import send_verification_code

    if has_active_celery_workers(app=send_verification_code_task.app):
        # Un worker est actif → envoi asynchrone via Redis
        send_verification_code_task.delay(client.client_token)
        logger.info(
            f"[send_code_async_or_sync] Tâche envoyée à Celery "
            f"pour client {client.client_token}"
        )
    else:
        # Aucun worker → exécution synchrone dans le processus Gunicorn
        logger.warning(
            f"[send_code_async_or_sync] Aucun worker Celery actif — "
            f"envoi synchrone pour client {client.client_token}"
        )
        send_verification_code(client)
