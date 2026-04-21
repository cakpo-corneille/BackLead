# tracking/models.py
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
    import re
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
        return int(float(s[:-1]) * 1024**3)
    if s.endswith('M'):
        return int(float(s[:-1]) * 1024**2)
    if s.endswith('K'):
        return int(float(s[:-1]) * 1024)
    try:
        return int(s)
    except ValueError:
        return None


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
    # Relation obligatoire
    client = models.ForeignKey(
        OwnerClient, on_delete=models.CASCADE, related_name='sessions'
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
    def total_mb(self):
        return round((self.bytes_downloaded + self.bytes_uploaded) / (1024 ** 2), 2)

    @property
    def download_mb(self):
        return round(self.bytes_downloaded / (1024 ** 2), 2)

    @property
    def upload_mb(self):
        return round(self.bytes_uploaded / (1024 ** 2), 2)
