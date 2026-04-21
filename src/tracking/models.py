# tracking/models.py
import re
import uuid
from django.db import models
from django.contrib.auth import get_user_model
from core_data.models import OwnerClient

User = get_user_model()


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


def parse_mikrotik_limit(s):
    """
    Convertit '10M' / '512k' / '---' en bytes.
    Retourne None si illimité ('---' ou vide).
    """
    if not s or s.strip() in ('---', '', '0'):
        return None
    s = s.strip().upper()
    if s.endswith('G'):
        return int(float(s[:-1]) * 1024 ** 3)
    if s.endswith('M'):
        return int(float(s[:-1]) * 1024 ** 2)
    if s.endswith('K'):
        return int(float(s[:-1]) * 1024)
    try:
        return int(s)
    except ValueError:
        return None


class TicketPlan(models.Model):
    """
    Plan tarifaire déclaré par l'owner depuis son dashboard.
    Sert de référence pour identifier automatiquement quel plan
    correspond à une session MikroTik via les rx-limit / tx-limit
    (ou la durée si limites = illimitées).
    """
    owner = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='ticket_plans'
    )
    name = models.CharField(max_length=100)
    price_fcfa = models.PositiveIntegerField(help_text="Prix du ticket en FCFA")
    duration_minutes = models.PositiveIntegerField(
        help_text="Durée de validité du ticket en minutes"
    )
    download_limit_mb = models.PositiveIntegerField(
        null=True, blank=True,
        help_text="Limite download en MB. Vide = illimité."
    )
    upload_limit_mb = models.PositiveIntegerField(
        null=True, blank=True,
        help_text="Limite upload en MB. Vide = illimité."
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['owner', 'price_fcfa']
        indexes = [
            models.Index(fields=['owner', 'is_active']),
        ]

    def __str__(self):
        return f"{self.name} ({self.price_fcfa} FCFA)"

    @property
    def download_limit_bytes(self):
        if self.download_limit_mb is None:
            return None
        return self.download_limit_mb * 1024 * 1024

    @property
    def upload_limit_bytes(self):
        if self.upload_limit_mb is None:
            return None
        return self.upload_limit_mb * 1024 * 1024


class ConnectionSession(models.Model):
    """
    Une session = un ticket WiFi = une connexion d'un client.
    Même client, tickets différents → sessions différentes.
    Mise à jour à chaque heartbeat (chaque refresh MikroTik de status.html).
    """

    # Relations
    owner = models.ForeignKey(
        User, on_delete=models.CASCADE,
        related_name='tracking_sessions'
    )
    client = models.ForeignKey(
        OwnerClient, on_delete=models.CASCADE, related_name='sessions'
    )
    ticket_plan = models.ForeignKey(
        TicketPlan, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='sessions',
        help_text="Plan correspondant identifié automatiquement"
    )

    # Identifiants réseau (depuis les data-* attributes MikroTik)
    mac_address          = models.CharField(max_length=17, db_index=True)
    ip_address           = models.GenericIPAddressField(null=True, blank=True)
    ticket_id            = models.CharField(max_length=128, null=True, blank=True, db_index=True)
    mikrotik_session_id  = models.CharField(max_length=128, null=True, blank=True)

    # Clé de session (pour enchaîner les heartbeats)
    session_key = models.UUIDField(default=uuid.uuid4, unique=True, db_index=True)

    # Timing
    started_at     = models.DateTimeField(auto_now_add=True)
    ended_at       = models.DateTimeField(null=True, blank=True)
    last_heartbeat = models.DateTimeField(auto_now=True)

    # Consommation (mise à jour à chaque heartbeat par MikroTik)
    uptime_seconds       = models.PositiveIntegerField(default=0)
    bytes_downloaded     = models.BigIntegerField(default=0)
    bytes_uploaded       = models.BigIntegerField(default=0)
    download_limit_bytes = models.BigIntegerField(null=True, blank=True)
    upload_limit_bytes   = models.BigIntegerField(null=True, blank=True)

    # État
    is_active = models.BooleanField(default=True, db_index=True)

    # Snapshot brut du dernier heartbeat (extensibilité, débogage)
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
        """Durée calculée. Utilise ended_at si disponible, sinon uptime MikroTik."""
        if self.ended_at:
            return int((self.ended_at - self.started_at).total_seconds())
        return self.uptime_seconds

    @property
    def duration_human(self):
        """Format lisible : '1h 23m 45s'."""
        total = self.duration_seconds
        h, rem = divmod(total, 3600)
        m, s = divmod(rem, 60)
        parts = []
        if h:
            parts.append(f"{h}h")
        if m:
            parts.append(f"{m}m")
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
