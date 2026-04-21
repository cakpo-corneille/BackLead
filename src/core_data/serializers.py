from rest_framework import serializers
from django.core.validators import RegexValidator
from django.conf import settings
from urllib.parse import urljoin

from .models import FormSchema, OwnerClient, ConflictAlert


# ============================================================================
# FORM SCHEMA SERIALIZER (Dashboard)
# ============================================================================

class FormSchemaSerializer(serializers.ModelSerializer):
    """
    Serializer pour les schémas de formulaire visibles dans le dashboard.
    
    Inclus :
    - Le snippet JS d'intégration
    - La version du schéma (read-only)
    - Les options double opt-in
    - logo (ImageField) en écriture, logo_url (URL absolue) en lecture
    - media_host : hostname du bucket de stockage en prod (None en dev local)
    """
    integration_snippet = serializers.SerializerMethodField()
    logo_url = serializers.SerializerMethodField()
    media_host = serializers.SerializerMethodField()

    class Meta:
        model = FormSchema
        fields = (
            'id', 'name', 'schema',
            'public_key', 'enable',
            'integration_snippet',
            'created_at', 'updated_at',
            'version',
            'opt',
            'conflict_strategy',
            'title', 'description', 'logo', 'logo_url', 'button_label',
            'media_host',
        )
        read_only_fields = (
            'id', 'public_key',
            'created_at', 'updated_at',
            'integration_snippet', 'version',
            'logo_url',
            'media_host',
        )

    def get_logo_url(self, obj):
        """Retourne l'URL absolue du logo ou None si aucun logo n'est défini."""
        if not obj.logo:
            return None
        request = self.context.get('request')
        if request:
            return request.build_absolute_uri(obj.logo.url)
        return obj.logo.url

    def get_media_host(self, obj):
        """
        Retourne le hostname du bucket de stockage média en production.
        Ex: "t3.storageapi.dev" si MEDIA_URL = "https://t3.storageapi.dev/bucket/media/"
        Retourne None en développement local (MEDIA_URL relatif sans hostname).
        """
        from urllib.parse import urlparse
        media_url = getattr(settings, 'MEDIA_URL', '')
        parsed = urlparse(media_url)
        return parsed.hostname or None

    def validate_logo(self, value):
        """Valide le logo uploade."""
        if value:
            if value.size > 2 * 1024 * 1024:
                raise serializers.ValidationError('Le logo ne doit pas depasser 2MB.')
            allowed_types = ['image/jpeg', 'image/png', 'image/jpg', 'image/webp']
            if value.content_type not in allowed_types:
                raise serializers.ValidationError(
                    'Format non supporte. Utilisez JPEG, PNG ou WebP.'
                )
        return value

    def validate_schema(self, value):
        """Valide la structure du schema JSON."""
        from .validators import validate_schema_format
        is_valid, message = validate_schema_format(value)
        if not is_valid:
            raise serializers.ValidationError(message)
        return value

    def validate(self, data):
        """Validation croisee entre opt et le contenu du schema."""
        double_opt = data.get('opt', getattr(self.instance, 'opt', False))
        schema = data.get('schema', getattr(self.instance, 'schema', {}))

        if double_opt:
            fields = schema.get('fields', [])
            has_phone = any(f.get('type') == 'phone' for f in fields)
            if not has_phone:
                raise serializers.ValidationError({
                    "opt": "Le Double Opt-In necessite la presence d'un champ de type 'phone' dans votre formulaire pour l'envoi des codes SMS."
                })

        return data

    def get_integration_snippet(self, obj):
        """
        Genere le snippet HTML d'integration pour le widget.
        Utilise build_absolute_uri pour obtenir le domaine correct.
        """
        request = self.context.get('request')

        script_name = 'widget.min.js' if not settings.DEBUG else 'widget.js'

        if request:
            base_url = request.build_absolute_uri('/')
            script_url = urljoin(base_url, settings.STATIC_URL + f'core_data/{script_name}')
        else:
            script_url = getattr(settings, 'WIDGET_SCRIPT_URL', f'/static/core_data/{script_name}')

        return (
            f'<script src="{script_url}" '
            f'data-public-key="{obj.public_key}" '
            f'data-mac="$(mac)"></script>'
        )


# ============================================================================
# OWNER CLIENT SERIALIZER (Dashboard)
# ============================================================================

class OwnerClientSerializer(serializers.ModelSerializer):
    """
    Serializer pour les leads collectes visibles dans le dashboard.
    Tags et notes sont modifiables par l'owner. Reste en read-only.
    """

    class Meta:
        model = OwnerClient
        fields = (
            'id', 'email', 'phone',
            'mac_address', 'payload',
            'client_token', 'is_verified', 'recognition_level',
            'tags', 'notes',
            'created_at', 'last_seen',
        )
        read_only_fields = (
            'id', 'email', 'phone',
            'mac_address', 'payload',
            'client_token', 'is_verified', 'recognition_level',
            'created_at', 'last_seen',
        )


# ============================================================================
# CONFLICT ALERT SERIALIZER (Dashboard)
# ============================================================================

class ConflictAlertSerializer(serializers.ModelSerializer):
    """
    Serializer pour les alertes de conflits.
    """
    existing_client_email = serializers.EmailField(source='existing_client.email', read_only=True)
    existing_client_phone = serializers.CharField(source='existing_client.phone', read_only=True)

    class Meta:
        model = ConflictAlert
        fields = (
            'id', 'existing_client', 'existing_client_email', 'existing_client_phone',
            'conflict_field', 'offending_payload', 'offending_mac',
            'status', 'created_at',
        )
        read_only_fields = (
            'id', 'existing_client', 'conflict_field', 'offending_payload', 'offending_mac',
            'created_at',
        )


# ============================================================================
# PUBLIC ENDPOINTS (/portal/*)
# ============================================================================

class RecognitionSerializer(serializers.Serializer):
    """
    Donnees envoyees par le widget pour reconnaitre automatiquement un client.
    client_token est optionnel (1ere connexion).
    """
    public_key = serializers.UUIDField()
    mac_address = serializers.CharField(
        validators=[RegexValidator(
            regex=r'^([0-9A-Fa-f]{2}[:-]){5}([0-9A-Fa-f]{2})$',
            message="Invalid MAC address format (ex: AA:BB:CC:DD:EE:FF)"
        )]
    )
    client_token = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True
    )


class SubmissionSerializer(serializers.Serializer):
    """
    Soumission d'un lead depuis le widget.
    Valide le payload contre le schema du FormSchema dynamiquement.
    """
    public_key = serializers.UUIDField()
    mac_address = serializers.CharField(
        validators=[RegexValidator(
            regex=r'^([0-9A-Fa-f]{2}[:-]){5}([0-9A-Fa-f]{2})$',
            message="Invalid MAC address format (ex: AA:BB:CC:DD:EE:FF)"
        )]
    )
    payload = serializers.JSONField()
    client_token = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True
    )
    verification_code = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True
    )

    def validate(self, attrs):
        """Validation globale : verifie le payload contre le schema."""
        public_key = attrs.get('public_key')
        payload = attrs.get('payload')

        try:
            form_schema = FormSchema.objects.get(public_key=public_key)
        except FormSchema.DoesNotExist:
            raise serializers.ValidationError({
                'public_key': 'Invalid public_key'
            })

        from .validators import validate_payload_against_schema

        is_valid, errors_dict, clean_payload = validate_payload_against_schema(
            payload,
            form_schema.schema,
            default_region="BJ"
        )

        if not is_valid:
            raise serializers.ValidationError({
                'payload': errors_dict
            })

        attrs['payload'] = clean_payload
        attrs['_form_schema'] = form_schema

        return attrs


class DoubleOptInSerializer(serializers.Serializer):
    """
    Validation d'un code de double opt-in.
    Champs : client_token, code.
    """
    client_token = serializers.CharField()
    code = serializers.CharField()


class ResendDoubleOptInSerializer(serializers.Serializer):
    """
    Demande de ré-expedition d'un code de double opt-in.
    Champ : client_token.
    """
    client_token = serializers.CharField()


class FormSchemaPublicSerializer(serializers.Serializer):
    """
    Donnees publiques d'un FormSchema renvoyees au widget lors du provisioning.

    Utilise comme serializer de sortie dans PortalViewSet.provision().
    Le service portal_services.provision() retourne un dict passe comme
    instance — DRF gere les dicts via Mapping dans get_attribute().

    Champs :
        schema          — structure des champs du formulaire
        enable          — formulaire actif ou non (widget s'arrete si False)
        opt             — active le parcours OTP SMS
        title           — titre affiche dans le header du widget
        description     — texte descriptif (CTA)
        button_label    — libelle du bouton de soumission
        logo_url        — URL absolue du logo du formulaire (nullable)
        owner           — { name, logo_url } infos publiques de l'owner
    """
    schema = serializers.JSONField()
    enable = serializers.BooleanField()
    opt = serializers.BooleanField()
    title = serializers.CharField()
    description = serializers.CharField()
    button_label = serializers.CharField()
    logo_url = serializers.URLField(allow_null=True, required=False)
    owner = serializers.DictField(required=False)
