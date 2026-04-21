# tracking/serializers.py
from rest_framework import serializers
from .models import TicketPlan, ConnectionSession


class HeartbeatSerializer(serializers.Serializer):
    """Valide et nettoie les données envoyées par tracker.js."""

    public_key  = serializers.UUIDField()
    mac_address = serializers.RegexField(
        r'^([0-9A-Fa-f]{2}[:\-]){5}[0-9A-Fa-f]{2}$',
        error_messages={'invalid': 'Format MAC invalide (ex: AA:BB:CC:DD:EE:FF)'}
    )
    session_key = serializers.UUIDField(required=False, allow_null=True)
    ip_address  = serializers.IPAddressField(required=False, allow_null=True, allow_blank=True)
    uptime      = serializers.CharField(required=False, allow_blank=True, default='')
    bytes_in    = serializers.CharField(required=False, allow_blank=True, default='0')
    bytes_out   = serializers.CharField(required=False, allow_blank=True, default='0')
    rx_limit    = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    tx_limit    = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    username    = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    session_id  = serializers.CharField(required=False, allow_null=True, allow_blank=True)


class EndSessionSerializer(serializers.Serializer):
    session_key = serializers.UUIDField()


class TicketPlanSerializer(serializers.ModelSerializer):
    class Meta:
        model = TicketPlan
        fields = [
            'id', 'name', 'price_fcfa', 'duration_minutes',
            'download_limit_mb', 'upload_limit_mb',
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


class ConnectionSessionSerializer(serializers.ModelSerializer):
    duration_seconds = serializers.IntegerField(read_only=True)
    duration_human   = serializers.CharField(read_only=True)
    total_mb         = serializers.FloatField(read_only=True)
    download_mb      = serializers.FloatField(read_only=True)
    upload_mb        = serializers.FloatField(read_only=True)
    plan_name        = serializers.CharField(source='ticket_plan.name', read_only=True, default=None)
    plan_price_fcfa  = serializers.IntegerField(source='ticket_plan.price_fcfa', read_only=True, default=None)
    client_email     = serializers.EmailField(source='client.email', read_only=True, default=None)
    client_phone     = serializers.CharField(source='client.phone', read_only=True, default=None)

    class Meta:
        model = ConnectionSession
        fields = [
            'id', 'session_key',
            'mac_address', 'ip_address', 'ticket_id',
            'started_at', 'ended_at', 'last_heartbeat',
            'uptime_seconds', 'bytes_downloaded', 'bytes_uploaded',
            'is_active',
            'duration_seconds', 'duration_human',
            'total_mb', 'download_mb', 'upload_mb',
            'plan_name', 'plan_price_fcfa',
            'client', 'client_email', 'client_phone',
            'user_agent',
        ]
        read_only_fields = fields
