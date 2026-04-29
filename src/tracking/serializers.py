# tracking/serializers.py
from rest_framework import serializers
from .models import TicketPlan, ConnectionSession, MikroTikRouter


# ----------------------------------------------------------------
# Heartbeat tracker.js
# ----------------------------------------------------------------

class HeartbeatSerializer(serializers.Serializer):
    """Valide les données envoyées par tracker.js depuis status.html."""

    public_key      = serializers.UUIDField()
    mac_address     = serializers.RegexField(
        r'^([0-9A-Fa-f]{2}[:\-]){5}[0-9A-Fa-f]{2}$',
        error_messages={'invalid': 'Format MAC invalide (ex: AA:BB:CC:DD:EE:FF)'}
    )
    session_key     = serializers.UUIDField(required=False, allow_null=True)
    ip_address      = serializers.IPAddressField(required=False, allow_null=True, allow_blank=True)
    uptime          = serializers.CharField(required=False, allow_blank=True, default='')
    session_timeout = serializers.CharField(required=False, allow_blank=True, default='')
    bytes_in        = serializers.CharField(required=False, allow_blank=True, default='0')
    bytes_out       = serializers.CharField(required=False, allow_blank=True, default='0')
    username        = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    session_id      = serializers.CharField(required=False, allow_null=True, allow_blank=True)


class EndSessionSerializer(serializers.Serializer):
    session_key = serializers.UUIDField()


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
# Routeurs MikroTik
# ----------------------------------------------------------------

class MikroTikRouterSerializer(serializers.ModelSerializer):
    """
    Sérialise un routeur MikroTik.
    - 'password' est en écriture seule (jamais renvoyé en lecture)
    - 'last_error' et 'last_synced_at' sont en lecture seule
    """
    # Champ virtuel pour la saisie du mot de passe (write-only)
    password = serializers.CharField(
        write_only=True,
        required=False,          # optionnel en update (on ne change pas forcément le mdp)
        allow_blank=False,
        style={'input_type': 'password'},
        help_text="Mot de passe API MikroTik (jamais retourné en lecture)"
    )
    # Indique si la dernière synchro s'est bien passée
    is_healthy = serializers.SerializerMethodField()

    class Meta:
        model  = MikroTikRouter
        fields = [
            'id', 'name', 'host', 'port', 'username', 'password',
            'is_active', 'last_synced_at', 'last_error', 'is_healthy',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'last_synced_at', 'last_error', 'created_at', 'updated_at']

    def get_is_healthy(self, obj) -> bool:
        """Routeur sain = dernière synchro sans erreur."""
        return obj.last_synced_at is not None and obj.last_error == ''

    def validate_port(self, v):
        if not (1 <= v <= 65535):
            raise serializers.ValidationError("Port invalide (1–65535).")
        return v

    def create(self, validated_data):
        password = validated_data.pop('password', None)
        if not password:
            raise serializers.ValidationError({"password": "Le mot de passe est obligatoire."})
        router = MikroTikRouter(**validated_data)
        router.set_password(password)
        router.save()
        return router

    def update(self, instance, validated_data):
        password = validated_data.pop('password', None)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        if password:
            instance.set_password(password)
        instance.save()
        return instance


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
    router_name           = serializers.CharField(source='router.name', read_only=True, default=None)

    class Meta:
        model  = ConnectionSession
        fields = [
            'id', 'session_key',
            'mac_address', 'ip_address', 'ticket_id',
            'started_at', 'ended_at', 'last_heartbeat',
            'session_timeout_seconds',
            'uptime_seconds', 'bytes_downloaded', 'bytes_uploaded',
            'is_active',
            'duration_seconds', 'duration_human',
            'total_mb', 'download_mb', 'upload_mb',
            'plan_name', 'plan_price_fcfa', 'plan_duration_minutes',
            'client', 'client_email', 'client_phone',
            'router_name', 'user_agent',
        ]
        read_only_fields = fields


# ----------------------------------------------------------------
# Snippet HTML à coller dans status.html MikroTik
# ----------------------------------------------------------------

def get_tracking_snippet(public_key, request=None, mode='full'):
    """
    Génère le script tag à coller dans status.html ou logout.html du hotspot MikroTik.
    """
    from django.conf import settings
    from urllib.parse import urljoin

    script_name = 'tracker.min.js' if not settings.DEBUG else 'tracker.js'

    if request:
        base_url   = request.build_absolute_uri('/')
        script_url = urljoin(base_url, settings.STATIC_URL + f'tracking/{script_name}')
    else:
        script_url = getattr(
            settings, 'TRACKER_SCRIPT_URL', f'/static/tracking/{script_name}'
        )

    if mode == 'logout':
        return (
            f'<script src="{script_url}" '
            f'data-public-key="{public_key}" '
            f'data-mac="$(mac)"></script>'
        )

    # Mode 'full' par défaut pour status.html
    return (
        f'<script src="{script_url}" '
        f'data-public-key="{public_key}" '
        f'data-mac="$(mac)" '
        f'data-ip="$(ip)" '
        f'data-uptime="$(uptime)" '
        f'data-session-timeout="$(session-timeout)" '
        f'data-bytes-in="$(bytes-in)" '
        f'data-bytes-out="$(bytes-out)" '
        f'data-username="$(username)" '
        f'data-session-id="$(session-id)"></script>'
    )
