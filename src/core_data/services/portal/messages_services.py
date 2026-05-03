import string
import secrets
import logging

from django.contrib.auth import get_user_model
from django.core.mail import send_mail
from django.conf import settings
from django.core.cache import cache

from core_data.models import FormSchema
from config.utils.sender import send_code_async_or_sync
from config.utils.sms_backend import get_sms_backend

logger = logging.getLogger(__name__)

User = get_user_model()

OTP_MAX_FAILS = 5


def generate_code(length=6):
    """Génère un code aléatoire à chiffres."""
    return ''.join(secrets.choice(string.digits) for _ in range(length))


def send_sms(phone_number, message):
    """
    Envoie un SMS via le provider configuré dans .env
    """
    backend = get_sms_backend()
    return backend.send(phone_number, message)


def send_verification_code(client, ttl_seconds=None):
    """
    Envoie un code de double opt-in uniquement par SMS pour un client donné.
    Stocke le code dans le cache APRÈS envoi réussi uniquement.
    
    Retourne :
        True  → si l'envoi s'est fait correctement
        False → en cas d'échec (loggé)
    """
    if ttl_seconds is None:
        ttl_seconds = settings.DOUBLE_OPT_TTL

    code = generate_code()
    cache_key = f"double_opt_{client.client_token}"

    business_name = (
        getattr(getattr(client.owner, "profile", None), "business_name", None)
        or "WIFI-ZONE"
    )

    form_schema = FormSchema.objects.filter(owner=client.owner).first()
    if not form_schema:
        logger.error(f"Aucun FormSchema trouvé pour owner {client.owner.id}")
        return False

    if not client.phone:
        logger.warning(f"Envoi SMS impossible : le client n'a pas fourni de numéro ({client.client_token})")
        return False

    try:
        result = send_sms(client.phone, f"Votre code de confirmation pour {business_name} est : {code}")
        
        if not result:
            logger.error(f"Échec de l'envoi du SMS à {client.phone}")
            return False
        
        cache.set(cache_key, code, timeout=ttl_seconds)
        logger.info(f"Code {code} stocké pour {client.client_token} (SMS)")
        return True

    except Exception as e:
        logger.error(f"Erreur lors de l'envoi du code par SMS : {e}")
        return False


def verify_code(client, code):
    """
    Vérifie si le code saisi correspond au code stocké.
    
    Protection brute-force : après 5 échecs consécutifs, le code est invalidé
    et le client doit en demander un nouveau.
    
    Args:
        client (OwnerClient): Instance de l'utilisateur
        code (str): Code saisi par l'utilisateur
    
    Returns:
        tuple: (bool, str) - (succès, message d'erreur si échec)
    """
    cache_key = f"double_opt_{client.client_token}"
    fail_key = f"otp_fails_{client.client_token}"

    stored_code = cache.get(cache_key)

    if not stored_code:
        cache.delete(fail_key)
        return False, "Code expiré ou invalide. Demandez un nouveau code."

    fail_count = cache.get(fail_key, 0)

    if fail_count >= OTP_MAX_FAILS:
        cache.delete(cache_key)
        cache.delete(fail_key)
        return False, "Code invalidé après trop de tentatives. Demandez un nouveau code."

    if stored_code != code:
        ttl = settings.DOUBLE_OPT_TTL
        cache.set(fail_key, fail_count + 1, timeout=ttl)
        remaining = OTP_MAX_FAILS - (fail_count + 1)
        if remaining <= 0:
            cache.delete(cache_key)
            cache.delete(fail_key)
            return False, "Code invalidé après trop de tentatives. Demandez un nouveau code."
        return False, f"Code incorrect. Il vous reste {remaining} tentative(s)."

    cache.delete(cache_key)
    cache.delete(fail_key)
    return True, ""


def resend_verification_code(client):
    """
    Renvoie un nouveau code de vérification.
    
    Limite : 1 code toutes les 60 secondes pour éviter le spam.
    
    Args:
        client (OwnerClient): Instance de l'utilisateur
    
    Returns:
        tuple: (bool, str) - (succès, message)
    """
    rate_limit_key = f"resend_rate_limit_{client.client_token}"
    
    if cache.get(rate_limit_key):
        return False, "Veuillez attendre 60 secondes avant de demander un nouveau code."
    
    send_code_async_or_sync(client)
    cache.set(rate_limit_key, True, timeout=60)
    
    return True, "Nouveau code envoyé avec succès."
