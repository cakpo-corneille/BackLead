"""
Stockage des conversations entre les owners et l'assistant IA Gemini.
"""
import uuid
from django.db import models
from django.contrib.auth import get_user_model

User = get_user_model()


class ChatConversation(models.Model):
    """Une conversation = un thread de discussion d'un owner avec l'IA."""
    owner = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='chat_conversations'
    )
    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False, db_index=True)
    title = models.CharField(max_length=200, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']
        indexes = [models.Index(fields=['owner', '-updated_at'])]

    def __str__(self):
        return f"Conversation {self.public_id} ({self.owner.email})"


class ChatMessage(models.Model):
    """Un message dans une conversation."""
    ROLE_USER = 'user'
    ROLE_MODEL = 'model'
    ROLE_CHOICES = [
        (ROLE_USER, 'User'),
        (ROLE_MODEL, 'Model'),
    ]

    conversation = models.ForeignKey(
        ChatConversation, on_delete=models.CASCADE, related_name='messages'
    )
    role = models.CharField(max_length=10, choices=ROLE_CHOICES)
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']
        indexes = [models.Index(fields=['conversation', 'created_at'])]

    def __str__(self):
        return f"[{self.role}] {self.content[:50]}"
