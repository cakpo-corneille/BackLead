import logging
from celery import shared_task
from django.contrib.auth import get_user_model

from .services import send_verification_code

logger = logging.getLogger(__name__)


@shared_task(
    bind=True, 
    max_retries=3, 
    default_retry_delay=60, 
    retry_backoff=True,  
    name='accounts.send_verification_code_task'
)
def send_verification_code_task(self, user_pk):
    """Tâche Celery pour envoyer l'email de vérification (double opt-in).

    Arguments:
        user_pk (int): PK de l'utilisateur
    """
    User = get_user_model()
    user = User.objects.filter(pk=user_pk).first()
    if not user:
        logger.warning(f"[accounts.tasks] User {user_pk} introuvable")
        return False

    try:
        send_verification_code(user)
        return True
    except Exception as exc:
        logger.exception(f"Erreur en envoyant l'email de vérification pour user {user_pk}")
        try:
            self.retry(exc=exc)
        except Exception:
            return False
