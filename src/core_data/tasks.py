import logging
from celery import shared_task
from .models import OwnerClient
from .services.portal.messages_services import send_verification_code

logger = logging.getLogger(__name__)


@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    retry_backoff=True,
    name='core_data.send_verification_code_task'
)
def send_verification_code_task(self, client_token):
    """
    Tâche Celery pour envoyer le code de vérification (double opt-in).
    
    Retry automatique si échec (max 3 tentatives, délai croissant).
    """
    client = OwnerClient.objects.filter(client_token=client_token).first()
    if not client:
        logger.warning(f"[core.tasks] Client introuvable pour token: {client_token}")
        return False

    try:
        result = send_verification_code(client)
        if result is True:
            logger.info(f"Code de vérification envoyé avec succès pour client {client.mac_address}")
            return True

        # Si l'envoi échoue, on force un retry
        raise Exception("send_verification_code returned False")

    except Exception as exc:
        logger.exception(
            f"Erreur en envoyant le code de vérification pour client {client.mac_address}"
        )
        try:
            # Retry automatique via Celery
            self.retry(exc=exc)
        except self.MaxRetriesExceededError:
            logger.error(f"Max retries atteints pour client {client.client_token}")
            return False


@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=120,
    name='core_data.send_whatsapp_alert_task'
)
def send_whatsapp_alert_task(self, alert_id):
    """
    Tâche Celery pour envoyer une alerte WhatsApp à l'owner.
    """
    from .models import ConflictAlert
    from config.utils.sender import _send_whatsapp_alert_sync
    
    alert = ConflictAlert.objects.filter(id=alert_id).first()
    if not alert:
        return False
        
    try:
        _send_whatsapp_alert_sync(alert)
        return True
    except Exception as exc:
        self.retry(exc=exc)



