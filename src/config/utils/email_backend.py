import logging
from django.core.mail import send_mail
from django.conf import settings

logger = logging.getLogger(__name__)

def send_email(subject, message, recipient_list, from_email=None, fail_silently=False, **kwargs):
    """
    Fonction centralisée pour l'envoi d'emails dans tout le backend.
    Gère les logs et assure une interface cohérente.
    """
    if not from_email:
        from_email = getattr(settings, 'DEFAULT_FROM_EMAIL', None)

    try:
        sent = send_mail(
            subject=subject,
            message=message,
            from_email=from_email,
            recipient_list=recipient_list,
            fail_silently=fail_silently,
            html_message=kwargs.get('html_message'),
            **{k: v for k, v in kwargs.items() if k != 'html_message'}
        )
        if sent:
            logger.info(f"Email envoyé avec succès à {recipient_list} (Sujet: {subject})")
            return True
        else:
            logger.warning(f"L'envoi d'email à {recipient_list} a échoué (Sujet: {subject})")
            return False
    except Exception as e:
        logger.error(f"Erreur lors de l'envoi de l'email à {recipient_list}: {str(e)}")
        if not fail_silently:
            raise e
        return False
