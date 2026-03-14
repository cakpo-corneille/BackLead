from django.db.models.signals import post_save
from django.dispatch import receiver
from django.conf import settings
from .models import OwnerProfile

import logging
logger = logging.getLogger(__name__)


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def manage_owner_profile(sender, instance, created, **kwargs):
    """Crée automatiquement un OwnerProfile pour chaque User."""
    if created:
        try:
            OwnerProfile.objects.get_or_create(
                user=instance,
                defaults={'business_name': f'WIFI-ZONE {instance.id}'}
            )
        except Exception as e:
            logger.warning(f"Failed to create OwnerProfile for user {instance.id}: {e}")
    else:
        # Update existing profile si nécessaire
        if hasattr(instance, 'profile'):
            try:
                instance.profile.save()
            except Exception as e:
                logger.warning(f"Failed to update OwnerProfile for user {instance.id}: {e}")
