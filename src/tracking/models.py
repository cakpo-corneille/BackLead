# tracking/models.py
import re
import uuid
import base64
import hashlib
from cryptography.fernet import Fernet

from django.db import models
from django.conf import settings
from django.contrib.auth import get_user_model
from core_data.models import OwnerClient

User = get_user_model()


# ----------------------------------------------------------------
# Utilitaires MikroTik
# ----------------------------------------------------------------

def parse_mikrotik_uptime(s):
    """
    Convertit '1d2h34m56s' en secondes.
    MikroTik omet les unités nulles : '5m12s', '2h3s' sont valides.
    """
    total = 0
    for val, unit in re.findall(r'(\d+)([dhms])', s or ''):
        multipliers = {'d': 86400, 'h': 3600, 'm': 60, 's': 1}
        total += int(val) * multipliers[unit]
    return total


def _get_fernet():
    """
    Construit une clé Fernet à partir du SECRET_KEY Django.
    Utilisé pour chiffrer/déchiffrer les mots de passe MikroTik.
    """
    raw = hashlib.sha256(settings.SECRET_KEY.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(raw))


# ----------------------------------------------------------------
# Plans tarifaires
# ----------------------------------------------------------------

class TicketPlan(models.Model):
    """
    Plan tarifaire : nom, durée, prix.
    Identification automatique via $(session-timeout) MikroTik.
    """
    owner = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='ticket_plans'
    )
    name             = models.CharField(max_length=100)
    price_fcfa       = models.PositiveIntegerField(help_text="Prix du ticket en FCFA")
    duration_minutes = models.PositiveIntegerField(
        help_text="Durée du ticket en minutes (ex: 60 pour 1h, 240 pour 4h)"
    )
    is_active  = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['owner', 'price_fcfa']
        indexes = [models.Index(fields=['owner', 'is_active'])]

    def __str__(self):
        return f"{self.name} — {self.duration_minutes} min ({self.price_fcfa} FCFA)"


# ----------------------------------------------------------------
# Routeurs MikroTik
# ----------------------------------------------------------------

class MikroTikRouter(models.Model):
    """
    Informations de connexion à un routeur MikroTik d'un owner.
    Le mot de passe est chiffré en base (Fernet / SECRET_KEY Django).
    Un owner peut avoir plusieurs routeurs (plusieurs points WiFi).
    """
    owner    = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='mikrotik_routers'
    )
    name     = models.CharField(
        max_length=100,
        help_text="Nom lisible (ex: Boutique principale)"
    )
    host     = models.CharField(
        max_length=255,
        help_text="IP ou domaine du routeur (ex: 192.168.88.1)"
    )
    port     = models.PositiveIntegerField(
        default=8728,
        help_text="Port API MikroTik (8728 par défaut, 8729 en SSL)"
    )
    username = models.CharField(
        max_length=100,
        help_text="Identifiant API MikroTik"
    )
    # Mot de passe chiffré — ne jamais lire directement ce champ
    _password_encrypted = models.BinaryField(
        db_column='password_encrypted',
        help_text="Mot de passe chiffré (Fernet)"
    )

    is_active      = models.BooleanField(default=True)
    last_synced_at = models.DateTimeField(
        null=True, blank=True,
        help_text="Dernière synchronisation réussie"
    )
    last_error     = models.TextField(
        blank=True, default='',
        help_text="Dernière erreur de connexion (vide si tout va bien)"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['owner', 'name']
        indexes = [models.Index(fields=['owner', 'is_active'])]

    def __str__(self):
        return f"{self.name} ({self.host}:{self.port})"

    # --- Gestion du mot de passe chiffré ---

    def set_password(self, raw_password):
        """Chiffre et stocke le mot de passe."""
        f = _get_fernet()
        self._password_encrypted = f.encrypt(raw_password.encode())

    def get_password(self):
        """Déchiffre et retourne le mot de passe en clair."""
        f = _get_fernet()
        return f.decrypt(bytes(self._password_encrypted)).decode()


# ----------------------------------------------------------------
# Sessions de connexion
# ----------------------------------------------------------------

class ConnectionSession(models.Model):
    """
    Une session = un ticket WiFi = une connexion d'un client.
    Créée au 1er heartbeat tracker.js.
    Mise à jour ensuite par la synchro Celery ↔ MikroTik.
    """
    owner = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='tracking_sessions'
    )
    client = models.ForeignKey(
        OwnerClient, on_delete=models.CASCADE, related_name='sessions'
    )
    ticket_plan = models.ForeignKey(
        TicketPlan, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='sessions',
        help_text="Plan identifié automatiquement via session-timeout"
    )
    # Routeur source (renseigné lors de la synchro Celery)
    router = models.ForeignKey(
        MikroTikRouter, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='sessions',
        help_text="Routeur MikroTik source de la session"
    )

    mac_address         = models.CharField(max_length=17, db_index=True)
    ip_address          = models.GenericIPAddressField(null=True, blank=True)
    ticket_id           = models.CharField(max_length=128, null=True, blank=True, db_index=True)
    mikrotik_session_id = models.CharField(max_length=128, null=True, blank=True)

    session_key = models.UUIDField(default=uuid.uuid4, unique=True, db_index=True)

    started_at     = models.DateTimeField(auto_now_add=True)
    ended_at       = models.DateTimeField(null=True, blank=True)
    last_heartbeat = models.DateTimeField(auto_now=True)

    # Durée TOTALE du ticket ($(session-timeout)) — clé d'identification du plan
    session_timeout_seconds = models.PositiveIntegerField(
        default=0,
        help_text="Durée totale accordée au ticket en secondes"
    )

    uptime_seconds   = models.PositiveIntegerField(default=0)
    bytes_downloaded = models.BigIntegerField(default=0)
    bytes_uploaded   = models.BigIntegerField(default=0)

    is_active     = models.BooleanField(default=True, db_index=True)
    user_agent    = models.CharField(max_length=512, blank=True, default='')
    last_raw_data = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ['-started_at']
        indexes = [
            models.Index(fields=['owner', '-started_at']),
            models.Index(fields=['owner', 'mac_address']),
            models.Index(fields=['owner', 'is_active']),
        ]

    @property
    def duration_seconds(self):
        if self.ended_at:
            return int((self.ended_at - self.started_at).total_seconds())
        return self.uptime_seconds

    @property
    def duration_human(self):
        total = self.duration_seconds
        h, rem = divmod(total, 3600)
        m, s = divmod(rem, 60)
        parts = []
        if h: parts.append(f"{h}h")
        if m: parts.append(f"{m}m")
        parts.append(f"{s}s")
        return " ".join(parts)

    @property
    def total_mb(self):
        return round((self.bytes_downloaded + self.bytes_uploaded) / (1024 ** 2), 2)

    @property
    def download_mb(self):
        return round(self.bytes_downloaded / (1024 ** 2), 2)

    @property
    def upload_mb(self):
        return round(self.bytes_uploaded / (1024 ** 2), 2)
