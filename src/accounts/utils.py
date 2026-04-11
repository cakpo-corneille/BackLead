# src/accounts/utils.py

import logging
logger = logging.getLogger(__name__)


def send_email_code_async_or_sync(user):
    from config.celery_utils import has_active_celery_workers
    from .tasks import send_verification_code_task
    from .services import send_verification_code

    if has_active_celery_workers(app=send_verification_code_task.app):
        send_verification_code_task.delay(user.id)
        logger.info(f"[send_email_code] Tâche envoyée à Celery pour user {user.id}")
    else:
        logger.warning(
            f"[send_email_code] Aucun worker Celery actif — "
            f"envoi synchrone pour user {user.id}"
        )
        send_verification_code(user)
