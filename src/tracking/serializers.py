# tracking/serializers.py
import re
from rest_framework import serializers
from .models import TicketPlan, ConnectionSession


# ----------------------------------------------------------------
# Utilitaire
# ----------------------------------------------------------------

def _normalize_mac(value):
    """Normalise une adresse MAC en majuscules avec deux-points."""
    normalized = value.upper().replace('-', ':')
    if not re.match(r'^([0-9A-F]{2}:){5}[0-9A-F]{2}$', normalized):
        raise serializers.ValidationError(
            "Format MAC invalide (ex: DC:A6:32:AA:BB:CC)"
        )
    return normalized


# ----------------------------------------------------------------
# Hotspot MikroTik (on-login / on-logout)
# ----------------------------------------------------------------

class HotspotLoginSerializer(serializers.Serializer):
    """Valide les données envoyées par le script on-login du routeur MikroTik."""

    mac          = serializers.CharField(max_length=17)   # $mac
    ip           = serializers.IPAddressField(required=False, allow_null=True, allow_blank=True)
    user         = serializers.CharField(max_length=128)  # $user (identifiant ticket)
    session_id   = serializers.CharField(max_length=128)  # $session-id
    uptime_limit = serializers.CharField(max_length=32)   # $uptime-limit  ex: '1h', '4h'
    owner_key    = serializers.UUIDField()

    # Optionnels — utiles pour debug
    server    = serializers.CharField(required=False, allow_blank=True, default='')
    interface = serializers.CharField(required=False, allow_blank=True, default='')

    def validate_mac(self, value):
        return _normalize_mac(value)


class HotspotLogoutSerializer(serializers.Serializer):
    """Valide les données envoyées par le script on-logout du routeur MikroTik."""

    mac        = serializers.CharField(max_length=17)
    session_id = serializers.CharField(max_length=128)
    uptime     = serializers.CharField(max_length=32)     # ex: '47m23s'
    bytes_in   = serializers.CharField(max_length=20, default='0')
    bytes_out  = serializers.CharField(max_length=20, default='0')
    cause      = serializers.CharField(max_length=64)     # ex: 'session-timeout'
    owner_key  = serializers.UUIDField()

    def validate_mac(self, value):
        return _normalize_mac(value)


# ----------------------------------------------------------------
# Plans tarifaires
# ----------------------------------------------------------------

class TicketPlanSerializer(serializers.ModelSerializer):
    class Meta:
        model  = TicketPlan
        fields = [
            'id', 'name', 'price_fcfa', 'duration_minutes',
            'is_active', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    def validate_price_fcfa(self, v):
        if v < 0:
            raise serializers.ValidationError("Le prix doit être positif.")
        return v

    def validate_duration_minutes(self, v):
        if v <= 0:
            raise serializers.ValidationError("La durée doit être supérieure à zéro.")
        return v


# ----------------------------------------------------------------
# Sessions (lecture seule — dashboard)
# ----------------------------------------------------------------

class ConnectionSessionSerializer(serializers.ModelSerializer):
    duration_seconds      = serializers.IntegerField(read_only=True)
    duration_human        = serializers.CharField(read_only=True)
    total_mb              = serializers.FloatField(read_only=True)
    download_mb           = serializers.FloatField(read_only=True)
    upload_mb             = serializers.FloatField(read_only=True)
    plan_name             = serializers.CharField(source='ticket_plan.name', read_only=True, default=None)
    plan_price_fcfa       = serializers.IntegerField(source='ticket_plan.price_fcfa', read_only=True, default=None)
    plan_duration_minutes = serializers.IntegerField(source='ticket_plan.duration_minutes', read_only=True, default=None)
    client_email          = serializers.EmailField(source='client.email', read_only=True, default=None)
    client_phone          = serializers.CharField(source='client.phone', read_only=True, default=None)
    client_first_name     = serializers.CharField(source='client.first_name', read_only=True, default=None)
    client_last_name      = serializers.CharField(source='client.last_name', read_only=True, default=None)
    status                = serializers.CharField(read_only=True)

    class Meta:
        model  = ConnectionSession
        fields = [
            'id', 'session_key',
            'mac_address', 'ip_address', 'ticket_id', 'mikrotik_session_id',
            'started_at', 'ended_at', 'last_heartbeat',
            'session_timeout_seconds',
            'uptime_seconds', 'bytes_downloaded', 'bytes_uploaded',
            'status',
            'duration_seconds', 'duration_human',
            'total_mb', 'download_mb', 'upload_mb',
            'plan_name', 'plan_price_fcfa', 'plan_duration_minutes',
            'client', 'client_email', 'client_phone', 'client_first_name', 'client_last_name',
        ]
        read_only_fields = fields


# ============================================================
# Snippets RouterOS MikroTik — générés dynamiquement par owner
# ============================================================

def get_tracking_snippet(owner_key: str, request=None) -> dict:
    """
    Génère les 3 snippets RouterOS MikroTik pour un gérant.

    Paramètres :
        owner_key — la public_key (UUID) du FormSchema du gérant.
        request   — HttpRequest Django (optionnel). S'il est fourni,
                    l'URL du backend est dérivée via request.build_absolute_uri('/'),
                    exactement comme get_integration_snippet() le fait pour le widget JS.
                    Si absent, fallback sur WIDGET_SCRIPT_URL puis URL de production.

    Retourne un dict avec 2 clés :
        - on_login   : script à coller dans "On Login" du profil hotspot
        - on_logout  : script à coller dans "On Logout" du profil hotspot
    """
    from django.conf import settings

    # Priorité 1 — request disponible : même logique que get_integration_snippet
    if request is not None:
        api_url = request.build_absolute_uri('/').rstrip('/')
    else:
        # Priorité 2 — dériver depuis WIDGET_SCRIPT_URL (même hôte)
        widget_url = getattr(settings, 'WIDGET_SCRIPT_URL', '')
        if widget_url:
            from urllib.parse import urlparse
            p = urlparse(widget_url)
            api_url = f"{p.scheme}://{p.netloc}"
        else:
            # Priorité 3 — fallback production
            api_url = 'https://backlead-web.onrender.com'

    login_url  = f"{api_url}/api/v1/sessions/login/"
    logout_url = f"{api_url}/api/v1/sessions/logout/"

    on_login = f"""\
# ── WiFiLeads — wl-login ────────────────────────────────────
# Coller dans : IP → Hotspot → Server Profiles → On Login
# RouterOS v6.49+ / v7.x
# ────────────────────────────────────────────────────────────
:local ownerKey "{owner_key}"
:local backendUrl "{login_url}"

:local postData ("mac=" . $mac . \\
    "&ip=" . $ip . \\
    "&user=" . $user . \\
    "&session_id=" . $"session-id" . \\
    "&uptime_limit=" . $"uptime-limit" . \\
    "&server=" . $server . \\
    "&interface=" . $interface . \\
    "&owner_key=" . $ownerKey)

/tool fetch \\
    url=$backendUrl \\
    http-method=post \\
    http-data=$postData \\
    output=none \\
    keep-result=no"""

    on_logout = f"""\
# ── WiFiLeads — wl-logout ───────────────────────────────────
# Coller dans : IP → Hotspot → Server Profiles → On Logout
# RouterOS v6.49+ / v7.x
# ────────────────────────────────────────────────────────────
:local ownerKey "{owner_key}"
:local backendUrl "{logout_url}"

:local postData ("mac=" . $mac . \\
    "&session_id=" . $"session-id" . \\
    "&uptime=" . $uptime . \\
    "&bytes_in=" . $"bytes-in" . \\
    "&bytes_out=" . $"bytes-out" . \\
    "&cause=" . $cause . \\
    "&owner_key=" . $ownerKey)

/tool fetch \\
    url=$backendUrl \\
    http-method=post \\
    http-data=$postData \\
    output=none \\
    keep-result=no"""

    return {
        'on_login':  on_login,
        'on_logout': on_logout,
    }
