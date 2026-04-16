"""
Services pour la gestion de l'authentification et de la vérification email.
"""
import random
import logging
from config.utils.email_backend import send_email
from django.conf import settings
from django.core.cache import cache

from accounts.utils import send_email_code_async_or_sync
from django.template.loader import render_to_string


logger = logging.getLogger(__name__)

def generate_verification_code():
    """
    Génère un code de vérification à 6 chiffres.
    
    Returns:
        str: Code à 6 chiffres (ex: '123456')
    """
    return ''.join([str(random.randint(0, 9)) for _ in range(6)])


def send_verification_code(user):
    """
    Génère et envoie un code de vérification par email.
    
    Le code est stocké dans Redis/cache avec une durée de vie de 10 minutes.
    
    Args:
        user (User): Instance de l'utilisateur
    
    Returns:
        str: Le code généré (utile pour les tests)
    """
    # Générer le code
    code = generate_verification_code()
    
    # Stocker dans le cache (Redis) avec TTL configurable
    cache_key = f'email_verification_{user.id}'
    ttl = settings.OTP_TTL
    cache.set(cache_key, code, timeout=ttl)
    
    # Construire l'email
    subject = 'Code de vérification - WiFi Marketing'
    message = f"""
Bonjour,

Merci de vous être inscrit sur WiFi Marketing !

Votre code de vérification est : {code}

Ce code est valide pendant {ttl // 60} minutes.

Si vous n'avez pas créé de compte, ignorez cet email.

Cordialement,
L'équipe WiFi Marketing
    """.strip()
    
    # Construire l'email HTML et texte
    ctx = {
        'code': code,
        'ttl_minutes': ttl // 60,
        'subject': subject
    }
    html_message = render_to_string('emails/auth/verification_code.html', ctx)

    # Envoyer l'email via l'utilité globale
    send_email(
        subject=subject,
        message=message,
        recipient_list=[user.email],
        html_message=html_message,
        fail_silently=False,
    )
    
    return code


def send_change_email_code(user, new_email):
    """
    Génère et envoie un code de vérification à une NOUVELLE adresse email.
    
    Le code et le nouvel email sont stockés dans le cache pour validation ultérieure.
    """
    code = generate_verification_code()
    
    # Clé spéciale pour le changement d'email
    cache_key = f'change_email_{user.id}'
    data = {
        'new_email': new_email,
        'code': code
    }
    ttl = settings.OTP_TTL
    cache.set(cache_key, data, timeout=ttl)
    
    subject = 'Confirmation de changement d\'email - WiFi Marketing'
    message = f"""
Bonjour,

Vous avez demandé à changer votre adresse email sur WiFi Marketing.

Votre code de confirmation est : {code}

Ce code est valide pendant {ttl // 60} minutes.

Si vous n'êtes pas à l'origine de cette demande, vous pouvez ignorer cet email.

Cordialement,
L'équipe WiFi Marketing
    """.strip()

    # Envoyer l'email à la NOUVELLE adresse via l'utilité globale (HTML)
    ctx = {
        'code': code,
        'ttl_minutes': ttl // 60,
        'subject': subject
    }
    html_message = render_to_string('emails/auth/change_email_code.html', ctx)

    send_email(
        subject=subject,
        message=message,
        recipient_list=[new_email],
        html_message=html_message,
        fail_silently=False,
    )
    
    return code




def verify_code(user, code):
    """
    Vérifie si le code saisi correspond au code stocké.
    
    Args:
        user (User): Instance de l'utilisateur
        code (str): Code saisi par l'utilisateur
    
    Returns:
        tuple: (bool, str) - (succès, message d'erreur si échec)
    """
    cache_key = f'email_verification_{user.id}'
    stored_code = cache.get(cache_key)
    
    if not stored_code:
        return False, "Code expiré ou invalide. Demandez un nouveau code."
    
    if stored_code != code:
        return False, "Code incorrect. Veuillez réessayer."
    
    # Code valide → supprimer du cache et marquer l'email comme vérifié
    cache.delete(cache_key)
    
    # Marquer email comme vérifié
    user.is_verify = True
    user.save()
    
    return True, ""


def resend_verification_code(user):
    """
    Renvoie un nouveau code de vérification.
    
    Limite : 1 code toutes les 60 secondes pour éviter le spam.
    
    Args:
        user (User): Instance de l'utilisateur
    
    Returns:
        tuple: (bool, str) - (succès, message)
    """
    # Vérifier le rate limiting (1 minute)
    rate_limit_key = f'email_verification_rate_limit_{user.id}'
    if cache.get(rate_limit_key):
        return False, "Veuillez attendre 60 secondes avant de demander un nouveau code."
    
    # Générer et envoyer le nouveau code
    send_email_code_async_or_sync(user)
    
    # Activer le rate limiting
    cache.set(rate_limit_key, True, timeout=60)
    
    return True, "Nouveau code envoyé avec succès."


def check_profile_completion(user):
    """
    Vérifie si le profil utilisateur est complet.
    
    Lecture de l'état calculé automatiquement par OwnerProfile.save()
    
    Args:
        user (User): Instance de l'utilisateur
    
    Returns:
        dict: {
            'is_complete': bool,
            'missing_fields': list,
            'completion_percentage': int,
            'has_business_name': bool,
            'has_logo': bool,
            'has_main_goal': bool,
            'has_location': bool
        }
    """
    profile = user.profile
    
    # Vérifier chaque champ obligatoire
    required_fields_check = {
        'business_name': bool(profile.business_name and profile.business_name != f'WIFI-ZONE {profile.user.id}'),
        'logo': bool(profile.logo and profile.logo.name != 'logos/default.png'),
        'nom': bool(profile.nom),
        'pays': bool(profile.pays),
        'ville': bool(profile.ville),
        'quartier': bool(profile.quartier),
        'main_goal': bool(profile.main_goal),
        "phone":bool(profile.phone_contact or profile.whatsapp_contact)
    }
    
    # Champs manquants
    missing_fields = [
        field for field, is_filled in required_fields_check.items()
        if not is_filled
    ]
    
    # Calcul pourcentage
    completed = sum(required_fields_check.values())
    total = len(required_fields_check)
    completion_percentage = int((completed / total) * 100) if total > 0 else 0
    
    return {
        'pass_onboarding':profile.pass_onboarding,
        'is_complete': profile.is_complete,  # Lu depuis le modèle
        'missing_fields': missing_fields,
        'completion_percentage': completion_percentage,
        'has_business_name': required_fields_check['business_name'],
        'has_logo': required_fields_check['logo'],
        'has_main_goal': required_fields_check['main_goal'],
        'has_contact':required_fields_check['phone'],
        'has_location': all([
            required_fields_check['pays'],
            required_fields_check['ville'],
            required_fields_check['quartier']
        ])
    }


def send_password_reset_code(email):
    """
    Génère et envoie un code de réinitialisation par email.
    
    Args:
        email (str): Email de l'utilisateur
    
    Returns:
        tuple: (success: bool, user_or_message: User|str)
    """
    from django.contrib.auth import get_user_model
    User = get_user_model()
    
    try:
        user = User.objects.get(email=email.lower().strip())
    except User.DoesNotExist:
        return False, "Aucun compte associé à cet email."
    
    # Générer le code
    code = generate_verification_code()
    
    # Stocker dans le cache avec clé différente
    cache_key = f'password_reset_{user.id}'
    ttl = settings.OTP_TTL
    cache.set(cache_key, code, timeout=ttl)
    
    # Construire l'email
    subject = 'Réinitialisation de mot de passe - WiFi Marketing'
    message = f"""
Bonjour,

Vous avez demandé la réinitialisation de votre mot de passe.

Votre code de vérification est : {code}

Ce code est valide pendant {ttl // 60} minutes.

Si vous n'avez pas demandé cette réinitialisation, ignorez cet email.

Cordialement,
L'équipe WiFi Marketing
    """.strip()
    
    send_email(
        subject=subject,
        message=message,
        recipient_list=[user.email],
        fail_silently=False,
    )
    
    return True, user


def reset_password_with_code(user_id, code, new_password):
    """
    Réinitialise le mot de passe après vérification du code.
    
    Args:
        user_id (int): ID de l'utilisateur
        code (str): Code à 6 chiffres
        new_password (str): Nouveau mot de passe
    
    Returns:
        tuple: (success: bool, error_message: str)
    """
    from django.contrib.auth import get_user_model
    User = get_user_model()
    
    cache_key = f'password_reset_{user_id}'
    stored_code = cache.get(cache_key)
    
    if not stored_code:
        return False, "Code expiré ou invalide."
    
    if stored_code != code:
        return False, "Code incorrect."
    
    # Code valide → réinitialiser le mot de passe
    try:
        user = User.objects.get(id=user_id)
        user.set_password(new_password)
        user.save()
        
        # Supprimer le code du cache
        cache.delete(cache_key)
        
        return True, ""
    except User.DoesNotExist:
        return False, "Utilisateur introuvable."


def change_password(user, old_password, new_password):
    """
    Change le mot de passe d'un utilisateur authentifié.
    
    Args:
        user (User): Instance de l'utilisateur
        old_password (str): Ancien mot de passe
        new_password (str): Nouveau mot de passe
    
    Returns:
        tuple: (success: bool, error_message: str)
    """
    if not user.check_password(old_password):
        return False, "Ancien mot de passe incorrect."
    
    user.set_password(new_password)
    user.save()
    
    return True, ""
