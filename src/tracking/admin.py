"""
Administration Django pour l'app tracking.

Fournit la gestion complète des plans tarifaires (TicketPlan)
et des sessions WiFi capturées (ConnectionSession), avec actions
en bulk, filtres, recherche et export CSV.
"""
import csv
from django.contrib import admin, messages
from django.http import HttpResponse
from django.utils import timezone
from django.utils.html import format_html

from .models import TicketPlan, ConnectionSession


# ============================================================
# TicketPlan
# ============================================================

@admin.register(TicketPlan)
class TicketPlanAdmin(admin.ModelAdmin):
    """Administration des plans tarifaires des owners."""

    list_display = (
        'name',
        'owner_email',
        'price_fcfa_display',
        'duration_display',
        'is_active',
        'sessions_count',
        'created_at',
    )
    list_filter = ('is_active', 'created_at', 'owner')
    search_fields = ('name', 'owner__email')
    list_select_related = ('owner',)
    ordering = ('owner', 'price_fcfa')
    date_hierarchy = 'created_at'
    readonly_fields = ('created_at', 'updated_at')
    actions = ('action_activate', 'action_deactivate')

    fieldsets = (
        ('Propriétaire', {
            'fields': ('owner',),
        }),
        ('Plan tarifaire', {
            'fields': ('name', 'price_fcfa', 'duration_minutes'),
        }),
        ('État', {
            'fields': ('is_active', 'created_at', 'updated_at'),
        }),
    )

    # --- Affichages calculés ---

    @admin.display(description='Owner', ordering='owner__email')
    def owner_email(self, obj):
        return obj.owner.email

    @admin.display(description='Prix', ordering='price_fcfa')
    def price_fcfa_display(self, obj):
        return f"{obj.price_fcfa:,} FCFA".replace(',', ' ')

    @admin.display(description='Durée', ordering='duration_minutes')
    def duration_display(self, obj):
        m = obj.duration_minutes
        if m >= 1440 and m % 1440 == 0:
            return f"{m // 1440}j"
        if m >= 60 and m % 60 == 0:
            return f"{m // 60}h"
        return f"{m} min"

    @admin.display(description='Sessions')
    def sessions_count(self, obj):
        return obj.sessions.count()

    # --- Actions bulk ---

    @admin.action(description='Activer les plans sélectionnés')
    def action_activate(self, request, queryset):
        n = queryset.update(is_active=True)
        self.message_user(request, f"{n} plan(s) activé(s).", level=messages.SUCCESS)

    @admin.action(description='Désactiver les plans sélectionnés')
    def action_deactivate(self, request, queryset):
        n = queryset.update(is_active=False)
        self.message_user(request, f"{n} plan(s) désactivé(s).", level=messages.WARNING)


# ============================================================
# ConnectionSession
# ============================================================

@admin.register(ConnectionSession)
class ConnectionSessionAdmin(admin.ModelAdmin):
    """Administration des sessions WiFi capturées via tracker.js."""

    list_display = (
        'short_session_key',
        'owner_email',
        'client_display',
        'mac_address',
        'ip_address',
        'plan_name',
        'started_at',
        'duration_human_display',
        'data_display',
        'status_badge',
    )
    list_filter = (
        'is_active',
        'owner',
        'ticket_plan',
        ('started_at', admin.DateFieldListFilter),
    )
    search_fields = (
        'mac_address',
        'ip_address',
        'ticket_id',
        'session_key',
        'client__email',
        'client__phone',
        'owner__email',
    )
    list_select_related = ('owner', 'client', 'ticket_plan')
    ordering = ('-started_at',)
    date_hierarchy = 'started_at'
    readonly_fields = (
        'session_key',
        'user_agent',
        'started_at',
        'ended_at',
        'last_heartbeat',
        'duration_seconds',
        'duration_human',
        'total_mb',
        'download_mb',
        'upload_mb',
        'last_raw_data',
    )
    actions = (
        'action_force_close',
        'action_export_csv',
    )

    fieldsets = (
        ('Identification', {
            'fields': ('session_key', 'owner', 'client', 'ticket_plan', 'user_agent'),
        }),
        ('Réseau MikroTik', {
            'fields': (
                'mac_address', 'ip_address', 'ticket_id', 'mikrotik_session_id',
            ),
        }),
        ('Consommation', {
            'fields': (
                'uptime_seconds', 'duration_human',
                'bytes_downloaded', 'download_mb',
                'bytes_uploaded', 'upload_mb',
                'total_mb',
                'download_limit_bytes', 'upload_limit_bytes',
            ),
        }),
        ('État', {
            'fields': ('is_active', 'started_at', 'ended_at', 'last_heartbeat'),
        }),
        ('Données brutes', {
            'classes': ('collapse',),
            'fields': ('last_raw_data',),
        }),
    )

    # --- Affichages calculés ---

    @admin.display(description='Session', ordering='session_key')
    def short_session_key(self, obj):
        return str(obj.session_key)[:8]

    @admin.display(description='Owner', ordering='owner__email')
    def owner_email(self, obj):
        return obj.owner.email

    @admin.display(description='Client')
    def client_display(self, obj):
        client = obj.client
        return client.email or client.phone or client.mac_address or f"#{client.id}"

    @admin.display(description='Plan', ordering='ticket_plan__name')
    def plan_name(self, obj):
        return obj.ticket_plan.name if obj.ticket_plan else '—'

    @admin.display(description='Durée')
    def duration_human_display(self, obj):
        return obj.duration_human

    @admin.display(description='Data (D/U)')
    def data_display(self, obj):
        return f"{obj.download_mb} / {obj.upload_mb} MB"

    @admin.display(description='Statut', ordering='is_active')
    def status_badge(self, obj):
        if obj.is_active:
            return format_html(
                '<span style="color:#fff;background:#16a34a;padding:2px 8px;border-radius:4px;">active</span>'
            )
        return format_html(
            '<span style="color:#fff;background:#6b7280;padding:2px 8px;border-radius:4px;">terminée</span>'
        )

    # --- Actions bulk ---

    @admin.action(description='Forcer la fermeture des sessions sélectionnées')
    def action_force_close(self, request, queryset):
        n = queryset.filter(is_active=True).update(
            is_active=False,
            ended_at=timezone.now(),
        )
        self.message_user(request, f"{n} session(s) fermée(s).", level=messages.SUCCESS)

    @admin.action(description='Exporter en CSV')
    def action_export_csv(self, request, queryset):
        response = HttpResponse(content_type='text/csv; charset=utf-8')
        filename = f"sessions_{timezone.now().date().isoformat()}.csv"
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        writer = csv.writer(response)
        writer.writerow([
            'session_key', 'owner', 'client_email', 'client_phone',
            'mac_address', 'ip_address', 'ticket_id', 'plan',
            'started_at', 'ended_at', 'duration_seconds',
            'download_mb', 'upload_mb', 'total_mb', 'is_active',
            'user_agent',
        ])
        for s in queryset.select_related('owner', 'client', 'ticket_plan'):
            writer.writerow([
                str(s.session_key),
                s.owner.email,
                s.client.email or '',
                s.client.phone or '',
                s.mac_address,
                s.ip_address or '',
                s.ticket_id or '',
                s.ticket_plan.name if s.ticket_plan else '',
                s.started_at.isoformat() if s.started_at else '',
                s.ended_at.isoformat() if s.ended_at else '',
                s.duration_seconds,
                s.download_mb,
                s.upload_mb,
                s.total_mb,
                s.is_active,
                s.user_agent,
            ])
        return response
