import logging
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.pagination import PageNumberPagination
from django.utils.decorators import method_decorator
from django.core.exceptions import ValidationError
from django.http import Http404
from django.core.cache import cache

from .validators import validate_schema_format

from .models import FormSchema, OwnerClient
from .serializers import (
    DoubleOptInSerializer,
    FormSchemaPublicSerializer,
    FormSchemaSerializer,
    OwnerClientSerializer,
    RecognitionSerializer,
    ResendDoubleOptInSerializer,
    SubmissionSerializer
)

from core_data.services.dashboard.analytics import  analytics_summary # type: ignore
from core_data.services.portal.portal_services import provision, recognize, ingest  # type: ignore
from core_data.services.portal.messages_services import resend_verification_code, verify_code # type: ignore
from .decorators import ratelimit_public_api

logger=logging.getLogger(__name__)

class FormSchemaViewSet(viewsets.ViewSet):
    """Gestion du schéma de formulaire (dashboard authentifié)."""
    permission_classes = [IsAuthenticated]

    @action(detail=False, methods=['get'])
    def config(self, request):
        """Récupère le schéma de l'owner connecté."""
        try:
            form_schema = request.user.form_schema
            serializer = FormSchemaSerializer(form_schema, context={'request': request})
            return Response(serializer.data)
        except FormSchema.DoesNotExist:
            return Response(
                {'detail': 'No form schema found. Create one first.'},
                status=status.HTTP_404_NOT_FOUND
            )

    @action(detail=False, methods=['post'])
    def update_schema(self, request):
        """Met à jour le schéma de formulaire."""
        schema_name = request.data.get('name')
        schema_data = request.data.get('schema')
        schema_type = request.data.get('is_default')
        schema_opt=request.data.get('double_opt_enable')
        schema_channel=request.data.get('preferred_channel')
        
        if not schema_data:
            return Response(
                {'detail': 'schema field is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            # Validation du schéma
            is_valid, error = validate_schema_format(schema_data)
            if not is_valid:
                return Response({"detail": error}, status=400)

            form_schema = request.user.form_schema
            form_schema.schema = schema_data
            form_schema.is_default = schema_type
            form_schema.double_opt_enable= schema_opt
            form_schema.preferred_channel= schema_channel
            
            # Mettre à jour le nom si fourni
            if schema_name:
                form_schema.name = schema_name
    
            form_schema.save()
            
        except FormSchema.DoesNotExist:
            # Créer le schéma s'il n'existe pas, en incluant les nouveaux champs
            form_schema = FormSchema.objects.create(
                owner=request.user,
                name=schema_name or 'default',
                schema=schema_data,
                is_default=schema_type if schema_type is not None else False, # Utiliser la valeur reçue
                double_opt_enable=schema_opt if schema_opt is not None else False, # Prévoir une valeur par défaut
                preferred_channel=schema_channel # Ce champ est obligatoire
            )

        
        serializer = FormSchemaSerializer(form_schema, context={'request': request})
        return Response(serializer.data)

    @action(detail=False, methods=['post'])
    def rotate_key(self, request):
        """Régénère la public_key."""
        try:
            form_schema = request.user.form_schema
            form_schema.rotate_public_key()
            return Response({
                'public_key': str(form_schema.public_key),
                'message': 'Public key rotated successfully. Update your router integration.'
            })
        except FormSchema.DoesNotExist:
            return Response(
                {'detail': 'No form schema found'},
                status=status.HTTP_404_NOT_FOUND
            )


class PortalViewSet(viewsets.ViewSet):
    """Endpoints publics pour le widget (portail captif)."""
    permission_classes = [AllowAny]

    @method_decorator(ratelimit_public_api(requests=10, duration=60))
    @action(detail=False, methods=['get'])
    def provision(self, request):
        """
        Retourne le schéma de formulaire et les infos de l'owner.
        
        Query params:
            - public_key (required): UUID de la clé publique
            - mac (optional): Adresse MAC du client
        """
        public_key = request.query_params.get('public_key')
        
        if not public_key:
            return Response(
                {'detail': 'public_key is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            data = provision(public_key)  
            return Response(data)
        except Http404:
            return Response(
                {'detail': 'Invalid public_key'},
                status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
        
            return Response(
                {'detail': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
            

    @method_decorator(ratelimit_public_api(requests=20, duration=60))
    @action(detail=False, methods=['post'])
    def recognize(self, request):
        """
        Vérifie si un client est déjà connu.
        
        Body:
            - public_key (required): UUID
            - mac_address (required): string
            - client_token (optional): string (pour reconnaissance cross-device)
        """
        serializer = RecognitionSerializer(data=request.data)
        
        if not serializer.is_valid():
            return Response(
                serializer.errors,
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            data = serializer.validated_data
            result = recognize(
                public_key=str(data['public_key']),
                mac_address=data['mac_address'],
                client_token=data.get('client_token')
            )
            if result['recognized'] and result['is_verified']:
                client=OwnerClient.objects.filter(client_token=result['client_token']).first()
                if client:
                    client.recognition_level+=1
                    client.save()
            return Response(result)
        except Http404:
            return Response(
                {'detail': 'Invalid public_key'},
                status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e: 
            return Response(
                {'detail': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


    @method_decorator(ratelimit_public_api(requests=20, duration=60))
    @action(detail=False, methods=['post'])
    def submit(self, request):
        """
        Enregistre les données d'un lead avec validation stricte.
        
        La validation du payload est faite dans le serializer.
        """
        serializer = SubmissionSerializer(data=request.data)
        
        # ✅ Validation automatique du payload ici
        if not serializer.is_valid():
            return Response(
                serializer.errors,
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            data = serializer.validated_data
            
            # ✅ Le payload est déjà validé et nettoyé
            result = ingest(
                form_schema=data['_form_schema'],  # ✅ Passer l'objet directement
                mac_address=data['mac_address'],
                payload=data['payload'],  # ✅ Déjà nettoyé
                client_token=data.get('client_token'),
                verification_code=data.get('verification_code')
            )
            
            # Gestion des différents cas de réponse
            if result.get('verification_pending'):
                return Response(result, status=status.HTTP_202_ACCEPTED)
            
            if 'error' in result:
                return Response(result, status=status.HTTP_400_BAD_REQUEST)
            
            return Response(result, status=status.HTTP_201_CREATED)
            
        except Exception as e:
            logger.exception("Erreur lors de l'ingestion")
            return Response(
                {'ok': False, 'detail': 'Internal server error'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
        

    @action(detail=False, methods=['post'])
    def confirm(self, request):
        """
        Confirme le double opt-in d’un client via le code reçu.
        """
        serializer = DoubleOptInSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data=serializer.validated_data
        client_token = data.get('client_token')
        code_input = data.get('code')

        if not client_token or not code_input:
            return Response(
                {"detail": "client_token et code sont requis"},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            client = OwnerClient.objects.get(client_token=client_token)
        except OwnerClient.DoesNotExist:
            return Response({"detail": "Client non trouvé"}, status=404)


        success, error_msg = verify_code(client, str(code_input))
        if not success:
            return Response({"ok": False, "detail": error_msg}, status=400)
        
        # Marquer email/phone comme vérifié
        client.is_verified = True
        client.save()
        return Response({"ok": True, "message": "Double opt-in confirmé"})



    @action(detail=False, methods=['post'])
    def resend(self, request):
        """
        Renvoie un nouveau code de double opt-in.
        """
        serializer = ResendDoubleOptInSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        client_token = data.get('client_token')

        if not client_token:
            return Response(
                {"detail": "client_token est requis"},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            client_data = OwnerClient.objects.get(client_token=client_token)
        except OwnerClient.DoesNotExist:
            return Response({"detail": "Client non trouvé"}, status=404)

        success, message = resend_verification_code(client_data)

        status_code = 200 if success else 429  # 429 = too many requests
        return Response({"ok": success, "message": message}, status=status_code)



class StandardResultsSetPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100



class AnalyticsViewSet(viewsets.ViewSet):
    """Analytics et leads pour le dashboard."""
    permission_classes = [IsAuthenticated]
    pagination_class = StandardResultsSetPagination

    @action(detail=False, methods=['get'])
    def summary(self, request):
        """Retourne les statistiques de base."""
        data = analytics_summary(request.user.id)
        return Response(data)

    @action(detail=False, methods=['get'])
    def leads(self, request):
        """Liste des leads collectés avec pagination."""
        queryset = OwnerClient.objects.filter(owner=request.user).select_related('owner').order_by('-last_seen')
        
        paginator = self.pagination_class()
        page = paginator.paginate_queryset(queryset, request)
        serializer = OwnerClientSerializer(page, many=True)

        return paginator.get_paginated_response(serializer.data)