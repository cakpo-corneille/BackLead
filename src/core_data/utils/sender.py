import logging
logger=logging.getLogger(__name__)


def send_code_async_or_sync(client):
    try:
        from ..tasks import send_verification_code_task
        send_verification_code_task.delay(client.client_token)
    except Exception as exc:
        from core_data.services.portal.messages_services import send_verification_code
        logger.warning(f"[send_code_async_or_sync] Celery down → fallback: {exc}")
        send_verification_code(client)
