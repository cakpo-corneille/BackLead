# tracking/models.py
import re
import uuid
import base64
import hashlib

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


# ----------------------------------------------------------------
# Plans tarifaires
# ----------------------------------------------------------------

class TicketPlan(models.Model):
    """
    Plan tarifaire : nom, durée, prix.
    Identification automatique via $(uptime-limit) MikroTik.
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
# Sessions de connexion
# ----------------------------------------------------------------

class ConnectionSession(models.Model):
    """
    Une session = un ticket WiFi = une connexion d'un client.
    Créée par le script on-login du routeur MikroTik.
    Fermée par le script on-logout ou par close_expired_sessions (Celery).
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
        help_text="Plan identifié automatiquement via uptime-limit"
    )

    mac_address         = models.CharField(max_length=17, db_index=True)
    ip_address          = models.GenericIPAddressField(null=True, blank=True)
    ticket_id           = models.CharField(max_length=128, null=True, blank=True, db_index=True)
    mikrotik_session_id = models.CharField(max_length=128, null=True, blank=True, db_index=True,
                                           help_text="$session-id MikroTik — clé de rapprochement avec on-logout")

    session_key = models.UUIDField(default=uuid.uuid4, unique=True, db_index=True)

    started_at     = models.DateTimeField(auto_now_add=True)
    ended_at       = models.DateTimeField(null=True, blank=True)
    last_heartbeat = models.DateTimeField(auto_now=True)

    # Durée TOTALE du ticket ($uptime-limit) — clé d'identification du plan
    session_timeout_seconds = models.PositiveIntegerField(
        default=0,
        help_text="Durée totale accordée au ticket en secondes ($uptime-limit)"
    )

    uptime_seconds   = models.PositiveIntegerField(default=0)
    bytes_downloaded = models.BigIntegerField(default=0)
    bytes_uploaded   = models.BigIntegerField(default=0)
    
    amount_fcfa = models.PositiveIntegerField(
    default=0,
    help_text="Prix du ticket au moment de la connexion (copie de TicketPlan.price_fcfa)"
    )
    
    is_active        = models.BooleanField(default=True, db_index=True)
    disconnect_cause = models.CharField(
        max_length=64,
        blank=True,
        default='',
        help_text="Raison de déconnexion transmise par MikroTik (session-timeout, lost-service, etc.)"
    )
   
    class Meta:
        ordering = ['-started_at']
        indexes = [
            models.Index(fields=['owner', '-started_at']),
            models.Index(fields=['owner', 'mac_address']),
            models.Index(fields=['owner', 'is_active']),
        ]

    @property
    def status(self):
        if self.is_active:
            return 'connecté'
        if self.disconnect_cause == 'expired-by-server':
            return 'expiré'
        return 'déconnecté'

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
