"""
Endpoints REST de l'assistant IA :
- Chat conversationnel : POST /assistant/chat/
- Liste / détail des conversations : GET /assistant/conversations/
- Génération de formulaire : POST /assistant/generate-form/
"""
from django.db.models import Count

from rest_framework import viewsets, mixins, status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import ChatConversation
from .serializers import (
    ChatConversationSerializer,
    ChatConversationListSerializer,
    ChatMessageSerializer,
    ChatRequestSerializer,
    FormGenerationRequestSerializer,
    FormGenerationResponseSerializer,
)
from .services import chat, generate_form_schema


class AssistantViewSet(viewsets.ViewSet):
    """Actions atomiques de l'assistant (chat + génération de formulaire)."""
    permission_classes = [IsAuthenticated]

    @action(detail=False, methods=['post'])
    def chat(self, request):
        """
        Envoie un message à l'IA. Crée une nouvelle conversation si
        `conversation_id` est absent, sinon poursuit la conversation.
        """
        serializer = ChatRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        conv = None
        conv_id = serializer.validated_data.get('conversation_id')
        if conv_id:
            try:
                conv = ChatConversation.objects.get(id=conv_id, owner=request.user)
            except ChatConversation.DoesNotExist:
                return Response(
                    {'detail': 'Conversation introuvable.'},
                    status=status.HTTP_404_NOT_FOUND,
                )

        conversation, assistant_msg = chat(
            owner=request.user,
            user_message=serializer.validated_data['message'],
            conversation=conv,
        )
        return Response({
            'conversation_id': conversation.id,
            'public_id': str(conversation.public_id),
            'reply': ChatMessageSerializer(assistant_msg).data,
        }, status=status.HTTP_200_OK)

    @action(detail=False, methods=['post'], url_path='generate-form')
    def generate_form(self, request):
        """
        Génère un schéma de formulaire à partir d'une description libre.
        Le frontend décide ensuite s'il l'enregistre via /api/v1/schema/.
        """
        serializer = FormGenerationRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            schema = generate_form_schema(serializer.validated_data['prompt'])
        except ValueError as exc:
            return Response(
                {'detail': str(exc)},
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
        except Exception:
            return Response(
                {'detail': "Service IA indisponible. Réessayez."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        return Response(
            FormGenerationResponseSerializer(schema).data,
            status=status.HTTP_200_OK,
        )


class ChatConversationViewSet(mixins.ListModelMixin,
                              mixins.RetrieveModelMixin,
                              mixins.DestroyModelMixin,
                              viewsets.GenericViewSet):
    """Lecture & suppression des conversations de l'owner connecté."""
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = ChatConversation.objects.filter(owner=self.request.user)
        if self.action == 'list':
            qs = qs.annotate(messages_count=Count('messages'))
        return qs

    def get_serializer_class(self):
        if self.action == 'list':
            return ChatConversationListSerializer
        return ChatConversationSerializer
