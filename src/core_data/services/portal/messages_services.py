import string
import secrets
import logging

from django.contrib.auth import get_user_model
from django.core.mail import send_mail
from django.conf import settings
from django.core.cache import cache

from core_data.models import FormSchema
from core_data.utils.sender import send_code_async_or_sync
from core_data.utils.sms_backend import get_sms_backend

logger = logging.getLogger(__name__)

User = get_user_model()




def generate_code(length=6):
    """Génère un code aléatoire à chiffres."""
    return ''.join(secrets.choice(string.digits) for _ in range(length))


def send_sms(phone_number, message):
    """
    Envoie un SMS via le provider configuré dans .env
    """
    backend = get_sms_backend()
    return backend.send(phone_number, message)

    

def send_verification_code(client, ttl_seconds=180):
    """
    Envoie un code de double opt-in (email ou téléphone) pour un client donné.
    - Ne recrée pas un code si un code valide existe déjà.
    - Respecte le canal préféré du FormSchema (email/phone) avec fallback.
    - Stocke le code dans le cache avec TTL.
    
    Retourne :
        True  → si l’envoi s'est fait correctement
        False → en cas d'échec (loggé)
    """
    code = generate_code()
    cache_key = f"double_opt_{client.client_token}"
    cache.set(cache_key, code, timeout=ttl_seconds)
  
        
    # Construction du message
    business_name = (
        getattr(getattr(client.owner, "profile", None), "business_name", None)
        or "WIFI-ZONE"
    )

    message = (
        f"Bonjour,\n\n"
        f"Votre code de confirmation pour {business_name} est : {code}\n"
        f"Il est valide pendant {ttl_seconds//60} minutes.\n\n"
        f"Si vous n'êtes pas à l'origine de cette demande, ignorez ce message."
    )


    # Récupération du schema sans déclencher d'exception HTTP
    form_schema = FormSchema.objects.filter(owner=client.owner).first()
    if not form_schema:
        logger.error(f"Aucun FormSchema trouvé pour owner {client.owner.id}")
        return False

    # Détermination du canal → toujours défini
    if form_schema.preferred_channel == "email" and client.email:
        channel = "email"
    elif form_schema.preferred_channel == "phone" and client.phone:
        channel = "phone"
    else:
        # Fallback
        channel = "email" if client.email else "phone"

    try:
        if channel == "email":
            if not client.email:
                logger.warning(f"Envoi email impossible : client sans email ({client.client_token})")
                return False

            mail_send=send_mail(
                subject="Votre code de vérification",
                message=message,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[client.email],
                fail_silently=False
            )
            if mail_send == 0:
                logger.error(f"Échec de l'envoi de l'email à {client.email}")
                return False
            
            # ✅ Stocker APRÈS succès confirmé
            cache.set(cache_key, code, timeout=ttl_seconds)
            logger.info(f"Code {code} stocké pour {client.client_token} (email)")
            return True

        elif channel == "phone":
            if not client.phone:
                logger.warning(f"Envoi SMS impossible : client sans numéro ({client.client_token})")
                return False
            
            result = send_sms(client.phone, f"Votre code : {code}")
            if not result:
                logger.error(f"Échec de l'envoi du SMS à {client.phone}")
                return False
            
            # ✅ Stocker APRÈS succès confirmé
            cache.set(cache_key, code, timeout=ttl_seconds)
            logger.info(f"Code {code} stocké pour {client.client_token} (SMS)")
            return True
        else:
            logger.error(f"Canal d'envoi inconnu : {channel}")
            return False

    except Exception as e:
        logger.error(f"Erreur lors de l'envoi du code via {channel} : {e}")
        return False



def verify_code(client, code):
    """
    Vérifie si le code saisi correspond au code stocké.
    
    Args:
        client (OwnerClient): Instance de l'utilisateur
        code (str): Code saisi par l'utilisateur
    
    Returns:
        tuple: (bool, str) - (succès, message d'erreur si échec)
    """
    cache_key = f"double_opt_{client.client_token}"
    stored_code = cache.get(cache_key)
    
   
    if not stored_code:
        return False, "Code expiré ou invalide. Demandez un nouveau code."
    
    if stored_code != code:
        return False, "Code incorrect. Veuillez réessayer."
    
    # Code valide → supprimer du cache et marquer l'email comme vérifié
    cache.delete(cache_key)
    
    return True, ""



def resend_verification_code(client):
    """
    Renvoie un nouveau code de vérification.
    
    Limite : 1 code toutes les 60 secondes pour éviter le spam.
    
    Args:
        user (User): Instance de l'utilisateur
    
    Returns:
        tuple: (bool, str) - (succès, message)
    """

    rate_limit_key = f"resend_rate_limit_{client.client_token}"
    
    if cache.get(rate_limit_key):
        return False, "Veuillez attendre 60 secondes avant de demander un nouveau code."
    
    send_code_async_or_sync(client)
    cache.set(rate_limit_key, True, timeout=60)  # ← Clé différente
    
    return True, "Nouveau code envoyé avec succès."
