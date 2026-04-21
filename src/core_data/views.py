import logging
from rest_framework import viewsets, status, filters
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.pagination import PageNumberPagination
from rest_framework import mixins
from django.utils.decorators import method_decorator
from django.core.exceptions import ValidationError
from django.http import Http404
from django.core.cache import cache

from django.shortcuts import get_object_or_404
from .validators import validate_schema_format

from .models import FormSchema, OwnerClient, ConflictAlert
from .serializers import (
    DoubleOptInSerializer,
    FormSchemaPublicSerializer,
    FormSchemaSerializer,
    OwnerClientSerializer,
    RecognitionSerializer,
    ResendDoubleOptInSerializer,
    SubmissionSerializer,
    ConflictAlertSerializer
)

from core_data.services.dashboard.analytics import  analytics_summary # type: ignore
from core_data.services.portal.portal_services import provision, recognize, ingest  # type: ignore
from core_data.services.portal.messages_services import resend_verification_code # type: ignore
from core_data.services.portal.verification_services import verify_client_code # type: ignore
from .decorators import ratelimit_public_api

from .filters import LeadFilter

from rest_framework.pagination import PageNumberPagination


class LeadPagination(PageNumberPagination):
    """Configuration de la pagination pour les leads."""
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100


class LeadViewSet(mixins.ListModelMixin,
                  mixins.RetrieveModelMixin,
                  mixins.UpdateModelMixin,
                  mixins.DestroyModelMixin,
                  viewsets.GenericViewSet):
    """
    Gestion opérationnelle des leads (CRM).
    - GET /api/v1/leads/ : Liste avec filtres et recherche.
    - PATCH /api/v1/leads/{id}/ : Édition des tags/notes.
    - DELETE /api/v1/leads/{id}/ : Suppression RGPD.
    - POST /api/v1/leads/{id}/resend-verification/ : Renvoi OTP.
    """
    permission_classes = [IsAuthenticated]
    serializer_class = OwnerClientSerializer
    pagination_class = LeadPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    
    filterset_class = LeadFilter
    search_fields = ['email', 'phone', 'mac_address']
    ordering_fields = ['created_at', 'last_seen', 'recognition_level']
    ordering = ['-created_at']

    def get_queryset(self):
        """Leads appartenant à l'owner connecté."""
        return OwnerClient.objects.filter(owner=self.request.user).order_by('-created_at')

    @action(detail=True, methods=['post'], url_path='resend-verification')
    def resend_verification(self, request, pk=None):
        """Renvoi manuel d'un code OTP à un client."""
        lead = self.get_object()
        
        if lead.is_verified:
            return Response({"detail": "Ce client est déjà vérifié."}, status=400)
            
        if not lead.client_token:
            return Response({"detail": "Token client manquant."}, status=400)

        success, message = resend_verification_code(lead.client_token)
        
        if success:
            return Response({"detail": "Code de vérification renvoyé avec succès."})
        else:
            return Response({"detail": message}, status=400)


class FormSchemaViewSet(viewsets.ViewSet):
    """
    Gestion du centre de contrôle du formulaire et de son intégration.
    """
    permission_classes = [IsAuthenticated]

    @action(detail=False, methods=['get'], url_path='config')
    def config(self, request):
        """Récupère le schéma et le snippet d'intégration."""
        try:
            form_schema = request.user.form_schema
            serializer = FormSchemaSerializer(form_schema, context={'request': request})
            return Response(serializer.data)
        except FormSchema.DoesNotExist:
            return Response(
                {"detail": "Action requise : Configurez votre formulaire."},
                status=status.HTTP_404_NOT_FOUND
            )

    @action(detail=False, methods=['post', 'patch'], url_path='update-schema')
    def update_schema(self, request):
        """Mise à jour du formulaire (Supporte POST et PATCH)."""
        form_schema = get_object_or_404(FormSchema, owner=request.user)
        serializer = FormSchemaSerializer(form_schema, data=request.data, partial=True, context={'request': request})
        
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=['post'], url_path='rotate-key')
    def rotate_key(self, request):
        """Régénère la clé publique de sécurité."""
        try:
            form_schema = request.user.form_schema
            form_schema.rotate_public_key()
            return Response({
                'public_key': str(form_schema.public_key),
                'message': 'Clé renouvelée avec succès. Mettez à jour votre intégration.'
            })
        except FormSchema.DoesNotExist:
            return Response({"detail": "Formulaire inexistant."}, status=404)


class AnalyticsViewSet(viewsets.ViewSet):
    """
    Indicateurs de performance et statistiques (Dashboard).
    """
    permission_classes = [IsAuthenticated]

    @action(detail=False, methods=['get'])
    def summary(self, request):
        """Récupère les statistiques compactes avec cache Redis."""
        data = analytics_summary(request.user.id)
        return Response(data)


class ConflictAlertViewSet(viewsets.ReadOnlyModelViewSet, mixins.UpdateModelMixin):
    """
    Gestion des alertes de conflits (Dashboard).
    """
    permission_classes = [IsAuthenticated]
    serializer_class = ConflictAlertSerializer

    def get_queryset(self):
        return ConflictAlert.objects.filter(owner=self.request.user)

    @action(detail=True, methods=['post'])
    def resolve(self, request, pk=None):
        """Marque une alerte comme résolue."""
        alert = self.get_object()
        alert.status = 'RESOLVED'
        alert.save()
        return Response({'status': 'Alerte marquée comme résolue.', 'current_status': alert.status})

    @action(detail=True, methods=['post'])
    def ignore(self, request, pk=None):
        """Marque une alerte comme ignorée."""
        alert = self.get_object()
        alert.status = 'IGNORED'
        alert.save()
        return Response({'status': 'Alerte ignorée.', 'current_status': alert.status})


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
            data = provision(public_key, request=request)
            serializer = FormSchemaPublicSerializer(data)
            return Response(serializer.data)
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
            if result['recognized']:
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

        # Utilisation de verify_client_code qui gère aussi la résolution automatique des alertes
        success, error_msg = verify_client_code(client, str(code_input))
        if not success:
            return Response({"ok": False, "detail": error_msg}, status=400)
        
        return Response({"ok": True, "message": "Double opt-in confirmé et alertes résolues"})



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
