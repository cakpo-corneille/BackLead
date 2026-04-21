# tracking/serializers.py
from rest_framework import serializers


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
