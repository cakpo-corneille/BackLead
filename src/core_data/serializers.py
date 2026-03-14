from rest_framework import serializers
from django.conf import settings
from urllib.parse import urljoin

from .models import FormSchema, OwnerClient


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
    """
    integration_snippet = serializers.SerializerMethodField()

    class Meta:
        model = FormSchema
        fields = (
            'id', 'name', 'schema',
            'public_key', 'is_default',
            'integration_snippet',
            'created_at', 'updated_at',
            'version',
            'double_opt_enable',
            'preferred_channel',
        )
        read_only_fields = (
            'id', 'public_key',
            'created_at', 'updated_at',
            'integration_snippet', 'version'
        )

    
    def get_integration_snippet(self, obj):
        """
        Génère le snippet HTML d'intégration pour le widget.
        Utilise build_absolute_uri pour obtenir le domaine correct.
        """
        request = self.context.get('request')

        # Utilise widget.min.js en production, widget.js en développement
        script_name = 'widget.min.js' if not settings.DEBUG else 'widget.js'
        
        if request:
            # Exemple : https://api.monsaas.com/
            base_url = request.build_absolute_uri('/')
            script_url = urljoin(base_url, settings.STATIC_URL + f'core_data/{script_name}')
        else:
            # Fallback utilisé si le serializer est appelé sans requête (ex: cron, admin)
            script_url = getattr(settings, 'WIDGET_SCRIPT_URL', f'/static/core_data/{script_name}')

        return (
            f'<script src="{script_url}" '
            f'data-public-key="{obj.public_key}"></script>'
        )


# ============================================================================
# OWNER CLIENT SERIALIZER (Dashboard)
# ============================================================================

class OwnerClientSerializer(serializers.ModelSerializer):
    """
    Serializer pour les leads collectés visibles dans le dashboard.
    
    Entièrement en read-only : l’admin/owner ne modifie pas manuellement les leads.
    """

    class Meta:
        model = OwnerClient
        fields = (
            'id', 'email', 'phone',
            'mac_address', 'payload',
            'client_token', 'is_verified','recognition_level',
            'created_at', 'last_seen',
        )
        read_only_fields = fields


# ============================================================================
# PUBLIC ENDPOINTS (/portal/*)
# ============================================================================

class RecognitionSerializer(serializers.Serializer):
    """
    Données envoyées par le widget pour reconnaître automatiquement un client.
    
    Notes :
    - client_token est optionnel (1ère connexion)
    """
    public_key = serializers.UUIDField()
    mac_address = serializers.CharField()
    client_token = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True
    )


class SubmissionSerializer(serializers.Serializer):
    """
    Soumission d'un lead depuis le widget.
    Valide le payload contre le schéma du FormSchema dynamiquement.
    """
    public_key = serializers.UUIDField()
    mac_address = serializers.CharField()
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
        """
        Validation globale : vérifie le payload contre le schema.
        """
        public_key = attrs.get('public_key')
        payload = attrs.get('payload')
        
        # Récupérer le FormSchema
        try:
            form_schema = FormSchema.objects.get(public_key=public_key)
        except FormSchema.DoesNotExist:
            raise serializers.ValidationError({
                'public_key': 'Invalid public_key'
            })
        
        # Valider le payload contre le schéma
        from .validators import validate_payload_against_schema
        
        is_valid, error_msg, clean_payload = validate_payload_against_schema(
            payload,
            form_schema.schema,
            default_region="BJ"
        )
        
        if not is_valid:
            raise serializers.ValidationError({
                'payload': error_msg
            })
        
        # Stocker le payload nettoyé et le form_schema pour la vue
        attrs['payload'] = clean_payload
        attrs['_form_schema'] = form_schema  # ✅ Évite un 2ème get_object_or_404
        
        return attrs


class DoubleOptInSerializer(serializers.Serializer):
    """
    Serializer utilisé pour valider un code de double opt-in.

    Champs :
        - client_token (str) : Identifie le client ayant reçu un code.
        - verification_code (str) : Code envoyé par email/SMS à vérifier.

    Ce serializer assure que :
        • les deux champs sont fournis,
        • ils sont de type string,
        • une réponse 400 propre est retournée si invalides.
    """
    client_token = serializers.CharField()
    code = serializers.CharField()


class ResendDoubleOptInSerializer(serializers.Serializer):
    """
    Serializer permettant de demander la ré-expédition d'un code
    de double opt-in.

    Champs :
        - client_token (str) : Identifie le client pour lequel renvoyer un code.

    Il garantit la validation :
        • format correct,
        • champ obligatoire,
        • réponse 400 cohérente en cas d’erreur.
    """
    client_token = serializers.CharField()


class FormSchemaPublicSerializer(serializers.Serializer):
    """
    Serializer des données publiques d’un FormSchema, utilisées
    par le widget frontal lors du provisioning.

    Champs :
        - public_key (UUID) : Identifiant public du schéma.
        - schema (dict) : Liste des champs du formulaire.
        - double_opt_enable (bool) : Active le double opt-in.
        - preferred_channel (str) : 'email' ou 'phone'.

    Ce serializer est optionnel techniquement mais fortement recommandé :
        • normalisation du format envoyé au widget,
        • documentation automatique (OpenAPI),
        • cohérence avec les autres endpoints.
    """
    public_key = serializers.UUIDField()
    schema = serializers.JSONField()
    double_opt_enable = serializers.BooleanField()
    preferred_channel = serializers.CharField()
    
