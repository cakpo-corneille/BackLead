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
    enable = models.BooleanField(
        default=True,
        help_text="Active ou désactive le formulaire sur le portail captif."
    )
    version = models.PositiveIntegerField(
        default=0,
        help_text="Version du schéma, augmente uniquement lors de changements structurels."
    )

    opt = models.BooleanField(
        default=False,
        help_text="Activer la vérification OTP par SMS."
    )

    CONFLICT_STRATEGY_CHOICES = [
        ('ALLOW', 'Laisser passer (Log uniquement)'),
        ('REQUIRE_OTP', 'Exiger une vérification OTP'),
    ]

    conflict_strategy = models.CharField(
        max_length=20,
        choices=CONFLICT_STRATEGY_CHOICES,
        default='ALLOW',
        help_text="Action à entreprendre lorsqu'un email ou téléphone est déjà utilisé par un autre appareil."
    )

    title = models.CharField(
        max_length=120,
        blank=True,
        default='Bienvenue !',
        help_text="Titre affiché en haut du formulaire widget."
    )
    description = models.TextField(
        blank=True,
        default='Remplissez ce formulaire pour vous connecter.',
        help_text="Description/sous-titre affiché dans le formulaire widget."
    )
    logo = models.ImageField(
        upload_to="logos/form",
        blank=True,
        null=True,
        help_text="Logo affiché dans le formulaire widget."
    )
    button_label = models.CharField(
        max_length=80,
        blank=True,
        default='Accéder au WiFi',
        help_text="Texte du bouton de soumission du formulaire."
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Form Schema"
        verbose_name_plural = "Form Schemas"

    def __str__(self):
        return f"{self.name} (v{self.version}) - {self.owner.email}"

    def _get_schema_fingerprint(self, schema_data):
        """Extrait la structure technique du JSON (nombre de champs, noms et types)."""
        if not schema_data or not isinstance(schema_data, dict) or 'fields' not in schema_data:
            return []
        fields = schema_data.get('fields', [])
        return [(f.get('name'), f.get('type')) for f in fields if isinstance(f, dict)]

    def save(self, *args, **kwargs):
            """Incrémente la version uniquement si la structure technique (champs/types) change."""
            if self.pk:
                dirty_fields = self.get_dirty_fields()
                if 'schema' in dirty_fields:
                    old_schema = dirty_fields['schema']
                    new_schema = self.schema
                    
                    # On compare l'empreinte technique (noms et types)
                    if self._get_schema_fingerprint(old_schema) != self._get_schema_fingerprint(new_schema):
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
    
    # Qualification (Section 11 Roadmap)
    tags = models.JSONField(default=list, blank=True, help_text="Tags pour qualifier le lead (ex: ['VIP', 'Nouveau']).")
    notes = models.TextField(null=True, blank=True, help_text="Notes internes du propriétaire sur ce client.")

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


class ConflictAlert(models.Model):
    """
    Historique des conflits détectés lors de la soumission du portail.
    """
    STATUS_CHOICES = [
        ('PENDING', 'En attente'),
        ('RESOLVED', 'Résolu'),
        ('IGNORED', 'Ignoré'),
    ]

    owner = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='conflict_alerts'
    )
    existing_client = models.ForeignKey(
        OwnerClient,
        on_delete=models.CASCADE,
        related_name='conflicts'
    )
    conflict_field = models.CharField(
        max_length=10,
        choices=[('email', 'Email'), ('phone', 'Téléphone')]
    )
    offending_payload = models.JSONField()
    offending_mac = models.CharField(max_length=17)
    
    status = models.CharField(
        max_length=10,
        choices=STATUS_CHOICES,
        default='PENDING'
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Conflit {self.conflict_field} - {self.owner.email} ({self.created_at})"

