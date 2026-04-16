import logging
import os
from django.conf import settings
from django.db.models.signals import post_save, post_delete, pre_save
from django.dispatch import receiver

from .models import FormSchema, OwnerClient
from .services.dashboard.analytics import invalidate_analytics_cache

logger = logging.getLogger(__name__)


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def create_default_form_schema(sender, instance, created, **kwargs):
    """
    Crée automatiquement un FormSchema par défaut lorsque
    qu'un nouvel utilisateur est enregistré.

    - Empêche la duplication grâce à get_or_create.
    - Ne bloque jamais la création utilisateur en cas d'erreur.
    - Initialise un schéma JSON minimal valide.

    Args:
        sender: Le modèle User
        instance: L'utilisateur créé
        created: Booléen indiquant si l'utilisateur vient d'être créé
    """
    if not created:
        return

    try:
        # Créer le schéma si inexistant
        FormSchema.objects.get_or_create(
            owner=instance,
            defaults={
                "name": "default",
                "schema": {
                    "fields": [
                        {"name": "nom", "label": "Nom", "placeholder": "votre nom", "type": "text", "required": True},
                        {"name": "prenom", "label": "Prénom", "placeholder": "votre prénom", "type": "text", "required": True},
                        {"name": "phone", "label": "Téléphone", "placeholder": "votre numéro", "type": "phone", "required": True},
                    ]
                },
                "enable": True,
                "double_opt_enable": False,
                "version": 0,
            }
        )
        logger.info(f"Default FormSchema created for user {instance.id}")

    except Exception as e:
        # Ne jamais casser la création d'un user
        logger.warning(
            f"Failed to create default FormSchema for user {instance.id} : {e}"
        )


@receiver([post_save, post_delete], sender=OwnerClient)
def invalidate_owner_analytics_cache(sender, instance, **kwargs):
    """
    Invalide le cache des analytics dès qu'un client est créé, 
    modifié ou supprimé.
    """
    invalidate_analytics_cache(instance.owner_id)


def _delete_logo_file(logo_field):
    """Supprime physiquement le fichier logo s'il existe."""
    if logo_field and logo_field.name:
        try:
            path = logo_field.path
            if os.path.isfile(path):
                os.remove(path)
                logger.info(f"Logo supprimé : {path}")
        except Exception as e:
            logger.warning(f"Impossible de supprimer le logo : {e}")


@receiver(post_delete, sender=FormSchema)
def auto_delete_logo_on_form_schema_delete(sender, instance, **kwargs):
    """
    Supprime le fichier logo du disque lorsqu'un FormSchema est supprimé,
    afin d'éviter les fichiers orphelins.
    """
    _delete_logo_file(instance.logo)


@receiver(pre_save, sender=FormSchema)
def auto_delete_old_logo_on_logo_update(sender, instance, **kwargs):
    """
    Supprime l'ancien fichier logo du disque lorsque le logo est remplacé,
    afin d'éviter l'accumulation de fichiers inutilisés.
    """
    if not instance.pk:
        return

    try:
        old_instance = FormSchema.objects.get(pk=instance.pk)
    except FormSchema.DoesNotExist:
        return

    old_logo = old_instance.logo
    new_logo = instance.logo

    if old_logo and old_logo != new_logo:
        _delete_logo_file(old_logo)
