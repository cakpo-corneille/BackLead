import logging
logger = logging.getLogger(__name__)

def send_code_async_or_sync(client):
    """
    Envoie le code de double opt-in de façon asynchrone si un worker
    Celery est disponible, sinon bascule en synchrone immédiat.
    """
    from config.celery_utils import has_active_celery_workers
    # Imports dynamiques pour éviter les dépendances circulaires entre config et core_data
    from core_data.tasks import send_verification_code_task
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


def notify_conflict_alert(alert):
    """
    Notifie le propriétaire d'un conflit détecté via WhatsApp.
    Utilise Celery si disponible.
    """
    from config.celery_utils import has_active_celery_workers
    from core_data.tasks import send_whatsapp_alert_task
    
    # Récupérer le numéro WhatsApp de l'owner depuis son profil
    owner_profile = getattr(alert.owner, 'profile', None)
    if not owner_profile or not owner_profile.whatsapp_contact:
        logger.warning(f"Impossible de notifier l'owner {alert.owner.id} : Pas de contact WhatsApp.")
        return False

    if has_active_celery_workers(app=send_whatsapp_alert_task.app):
        send_whatsapp_alert_task.delay(alert.id)
        logger.info(f"Alerte WhatsApp envoyée à Celery pour l'alerte {alert.id}")
    else:
        # Synchrone
        _send_whatsapp_alert_sync(alert)


def _send_whatsapp_alert_sync(alert):
    """Logique synchrone d'envoi WhatsApp."""
    owner_profile = alert.owner.profile
    whatsapp_number = owner_profile.whatsapp_contact
    
    business_name = owner_profile.business_name or "Votre WIFI-ZONE"
    client_name = alert.existing_client.payload.get('nom', 'un client existant')
    
    message = (
        f"🚨 *Alerte Conflit - {business_name}*\n\n"
        f"Un utilisateur tente d'utiliser les coordonnées de *{client_name}* ({alert.conflict_field}) "
        f"sur un nouvel appareil (MAC: {alert.offending_mac}).\n\n"
        f"⚠️ Action requise sur votre dashboard."
    )
    
    # Pour l'instant on utilise le SMS backend comme proxy ou une console dédiée
    from config.utils.sms_backend import get_sms_backend
    backend = get_sms_backend()
    return backend.send(whatsapp_number, message)
