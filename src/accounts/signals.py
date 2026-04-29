import os
from django.db.models.signals import post_save, post_delete, pre_save
from django.dispatch import receiver
from django.conf import settings
from .models import OwnerProfile

import logging
logger = logging.getLogger(__name__)



@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def manage_owner_profile(sender, instance, created, **kwargs):
    """Crée ou met à jour l'OwnerProfile."""
    if created:
        try:
            OwnerProfile.objects.get_or_create(
                user=instance,
                defaults={'business_name': f'WIFI-ZONE {instance.id}'}
            )
        except Exception as e:
            logger.warning(f"Failed to create OwnerProfile for user {instance.id}: {e}")
    else:
        if hasattr(instance, 'profile'):
            try:
                instance.profile.save()
            except Exception as e:
                logger.warning(f"Failed to update OwnerProfile for user {instance.id}: {e}")

@receiver(post_delete, sender=OwnerProfile)
def auto_delete_file_on_delete(sender, instance, **kwargs):
    """Supprime le logo du stockage physique après la suppression du profil."""
    if instance.logo and instance.logo.name != 'logos/profile/default.png':
        try:
            if os.path.isfile(instance.logo.path):
                os.remove(instance.logo.path)
                logger.info(f"Logo profil supprimé : {instance.logo.path}")
        except Exception as e:
            logger.warning(f"Failed to delete logo file for profile {instance.id}: {e}")


@receiver(pre_save, sender=OwnerProfile)
def auto_delete_old_logo_on_logo_update(sender, instance, **kwargs):
    """
    Supprime l'ancien logo du disque lorsque le logo du profil est remplacé,
    afin d'éviter l'accumulation de fichiers inutilisés.
    """
    if not instance.pk:
        return

    try:
        old_instance = OwnerProfile.objects.get(pk=instance.pk)
    except OwnerProfile.DoesNotExist:
        return

    old_logo = old_instance.logo
    new_logo = instance.logo

    default_logo = 'logos/profile/default.png'
    if old_logo and old_logo != new_logo and old_logo.name != default_logo:
        try:
            if os.path.isfile(old_logo.path):
                os.remove(old_logo.path)
                logger.info(f"Ancien logo profil supprimé : {old_logo.path}")
        except Exception as e:
            logger.warning(f"Impossible de supprimer l'ancien logo profil : {e}")
