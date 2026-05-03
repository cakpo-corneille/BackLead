from django.contrib import admin
from .models import ChatConversation, ChatMessage


class ChatMessageInline(admin.TabularInline):
    model = ChatMessage
    extra = 0
    readonly_fields = ('role', 'content', 'created_at')
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(ChatConversation)
class ChatConversationAdmin(admin.ModelAdmin):
    list_display = ('id', 'owner_email', 'title', 'messages_count', 'updated_at')
    list_filter = ('owner', 'created_at')
    search_fields = ('title', 'owner__email', 'public_id')
    list_select_related = ('owner',)
    readonly_fields = ('public_id', 'created_at', 'updated_at')
    date_hierarchy = 'updated_at'
    inlines = [ChatMessageInline]

    @admin.display(description='Owner', ordering='owner__email')
    def owner_email(self, obj):
        return obj.owner.email

    @admin.display(description='Messages')
    def messages_count(self, obj):
        return obj.messages.count()


@admin.register(ChatMessage)
class ChatMessageAdmin(admin.ModelAdmin):
    list_display = ('id', 'conversation', 'role', 'short_content', 'created_at')
    list_filter = ('role', 'created_at')
    search_fields = ('content', 'conversation__owner__email')
    list_select_related = ('conversation', 'conversation__owner')
    readonly_fields = ('conversation', 'role', 'content', 'created_at')

    @admin.display(description='Contenu')
    def short_content(self, obj):
        return obj.content[:80] + ('…' if len(obj.content) > 80 else '')
