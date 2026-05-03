import logging
from django.db.models.signals import post_save
from django.dispatch import receiver

logger = logging.getLogger(__name__)


@receiver(post_save, sender='accounts.Owner')
def create_default_subscription(sender, instance, created, **kwargs):
    """
    Cree automatiquement un abonnement Free/Trial pour les nouveaux owners.
    """
    if created:
        from .models import Plan, Subscription
        
        # Chercher le plan Free ou le premier plan disponible
        free_plan = Plan.objects.filter(slug='free', is_active=True).first()
        if not free_plan:
            free_plan = Plan.objects.filter(is_active=True).order_by('price_monthly').first()
        
        if free_plan:
            try:
                Subscription.objects.create(
                    owner=instance,
                    plan=free_plan
                )
                logger.info(f"[Signal] Created default subscription for owner {instance.id}")
            except Exception as e:
                logger.error(f"[Signal] Error creating subscription for owner {instance.id}: {e}")
