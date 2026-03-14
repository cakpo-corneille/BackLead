import logging
logger=logging.getLogger(__name__)


def send_email_code_async_or_sync(user):
    from .tasks import send_verification_code_task
    try:
        send_verification_code_task.delay(user.id)
    except Exception as exc:
        from accounts.services import send_verification_code
        logger.warning(f"[send_email_code_async_or_sync] Celery down → fallback: {exc}")
        send_verification_code(user)
