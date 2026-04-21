from django.contrib import admin
from .models import TicketPlan, ConnectionSession


@admin.register(TicketPlan)
class TicketPlanAdmin(admin.ModelAdmin):
    list_display = (
        'name', 'owner', 'price_fcfa', 'duration_minutes',
        'download_limit_mb', 'upload_limit_mb', 'is_active',
    )
    list_filter = ('is_active', 'owner')
    search_fields = ('name', 'owner__email')
    ordering = ('owner', 'price_fcfa')


@admin.register(ConnectionSession)
class ConnectionSessionAdmin(admin.ModelAdmin):
    list_display = (
        'session_key', 'owner', 'client', 'mac_address',
        'ticket_plan', 'started_at', 'ended_at',
        'duration_human', 'total_mb', 'is_active',
    )
    list_filter = ('is_active', 'owner', 'ticket_plan')
    search_fields = (
        'mac_address', 'ip_address', 'ticket_id',
        'client__email', 'client__phone', 'owner__email',
    )
    readonly_fields = (
        'session_key', 'started_at', 'ended_at', 'last_heartbeat',
        'duration_seconds', 'duration_human', 'total_mb',
        'download_mb', 'upload_mb', 'last_raw_data',
    )
    ordering = ('-started_at',)
    date_hierarchy = 'started_at'
