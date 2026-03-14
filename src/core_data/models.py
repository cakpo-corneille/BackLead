import uuid
from django.db import models
from django.contrib.auth import get_user_model
from dirtyfields import DirtyFieldsMixin


User = get_user_model()


class FormSchema(DirtyFieldsMixin, models.Model):
    """
    Schéma dynamique utilisé pour collecter les informations des utilisateurs.
    Chaque owner possède un schéma unique.
    """
    owner = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name='form_schema',
        help_text="Le propriétaire de ce schéma"
    )
    name = models.CharField(
        max_length=120,
        default='default',
        help_text="Nom du schéma."
    )
    schema = models.JSONField(
        help_text="Structure du formulaire (JSON)."
    )
    public_key = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        db_index=True,
        editable=False,
        help_text="Identifiant public utilisé dans le widget."
    )
    is_default = models.BooleanField(
        default=True,
        help_text="Définit si ce schéma est celui par défaut."
    )
    version = models.PositiveIntegerField(
        default=0,
        help_text="Version du schéma, augmente à chaque modification."
    )

    double_opt_enable = models.BooleanField(
        default=True,
        help_text="Activer le double opt-in pour email/SMS."
    )
    preferred_channel = models.CharField(
        max_length=5,
        default="email",
        choices=[("email", "email"), ("phone", "phone")],
        help_text="Canal préféré pour envoyer le code de vérification."
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Form Schema"
        verbose_name_plural = "Form Schemas"

    def __str__(self):
        return f"{self.name} (v{self.version}) - {self.owner.email}"

    def save(self, *args, **kwargs):
            """Incrémente la version uniquement si le schéma change."""
            if self.pk and self.is_dirty(check_relationship=False):
                dirty_fields = self.get_dirty_fields()
                if 'schema' in dirty_fields:
                    self.version += 1
            super().save(*args, **kwargs)

    def rotate_public_key(self):
        """Change la clé publique sans toucher à la version."""
        self.public_key = uuid.uuid4()
        super(FormSchema, self).save(update_fields=['public_key'])


class OwnerClient(models.Model):
    """
    Chaque entrée correspond à une connexion WiFi d’un utilisateur unique
    identifié par son adresse MAC.
    """
    owner = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='collected_data'
    )
    mac_address = models.CharField(
        max_length=17,
        db_index=True,
        help_text="Adresse MAC du device."
    )
    payload = models.JSONField(help_text="Données brutes envoyées par l'utilisateur.")
    email = models.EmailField(
        max_length=254,
        null=True,
        blank=True,
        db_index=True
    )
    phone = models.CharField(
        max_length=40,
        null=True,
        blank=True,
        db_index=True
    )
    client_token = models.CharField(
        max_length=64,
        null=True,
        blank=True,
        help_text="Token interne pour reconnaître le client."
    )
    is_verified = models.BooleanField(default=False)
    recognition_level=models.PositiveIntegerField(default=0)

    last_seen = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Client Data"
        verbose_name_plural = "Client Data"
        unique_together = [
            ('owner', 'mac_address'),
            ('owner', 'client_token')
        ]
        indexes = [
            models.Index(fields=['owner', 'email']),
            models.Index(fields=['owner', 'phone']),
            models.Index(fields=['owner', '-created_at']),
            models.Index(fields=['owner', '-last_seen'])
        ]

    def __str__(self):
        return f"{self.mac_address} - {self.owner.email}"
