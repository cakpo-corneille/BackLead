from rest_framework import serializers
from .models import ChatConversation, ChatMessage


class ChatMessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = ChatMessage
        fields = ['id', 'role', 'content', 'created_at']
        read_only_fields = fields


class ChatConversationSerializer(serializers.ModelSerializer):
    messages = ChatMessageSerializer(many=True, read_only=True)

    class Meta:
        model = ChatConversation
        fields = ['id', 'public_id', 'title', 'created_at', 'updated_at', 'messages']
        read_only_fields = fields


class ChatConversationListSerializer(serializers.ModelSerializer):
    """Version sans messages pour l'index des conversations."""
    last_message_at = serializers.DateTimeField(source='updated_at', read_only=True)
    messages_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = ChatConversation
        fields = ['id', 'public_id', 'title', 'created_at',
                  'last_message_at', 'messages_count']
        read_only_fields = fields


class ChatRequestSerializer(serializers.Serializer):
    message = serializers.CharField(min_length=1, max_length=4000, trim_whitespace=True)
    conversation_id = serializers.IntegerField(required=False, allow_null=True)


class FormGenerationRequestSerializer(serializers.Serializer):
    prompt = serializers.CharField(min_length=5, max_length=2000, trim_whitespace=True)


class FormGenerationResponseSerializer(serializers.Serializer):
    title = serializers.CharField()
    description = serializers.CharField(allow_blank=True)
    button_label = serializers.CharField()
    fields = serializers.ListField(child=serializers.DictField())
