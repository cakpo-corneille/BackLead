import logging
from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import FormSchema

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
                        {"name": "email", "label": "Email", "placeholder": "votre email", "type": "email", "required": True},
                    ]
                },
                "is_default": True,
                "version": 0,
            }
        )
        logger.info(f"Default FormSchema created for user {instance.id}")

    except Exception as e:
        # Ne jamais casser la création d'un user
        logger.warning(
            f"Failed to create default FormSchema for user {instance.id} : {e}"
        )
