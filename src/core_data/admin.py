from django.contrib import admin
from django.contrib.admin import helpers
from django.template.response import TemplateResponse
from django.utils.html import format_html
from django.http import HttpResponse
import csv
import logging

from .models import FormSchema, OwnerClient

logger = logging.getLogger(__name__)


# ================================
# ADMIN : FormSchema
# ================================

@admin.register(FormSchema)
class FormSchemaAdmin(admin.ModelAdmin):
    """
    Administration des schémas de formulaire.
    Permet de gérer les formulaires créés par les owners,
    leurs clés publiques, paramètres de sécurité et timestamps.
    """

    list_display = (
        'owner__profile',
        'public_key_short',
        'is_default',
        'version',
        'double_opt_enable',
        'preferred_channel',
        'created_at'
    )
    
    search_fields = ('owner__email', 'public_key')
    list_filter = ('is_default', 'double_opt_enable', 'preferred_channel', 'created_at')
    readonly_fields = ('public_key', 'version', 'created_at', 'updated_at')
    actions = ['rotate_public_key_action']
    list_display_links = ( 'owner__profile',)
    ordering = ('version',)  


    fieldsets = (
        ('Owner', {
            'fields': ('owner',)
        }),
        ('Schema', {
            'fields': ('name','schema', 'is_default', 'version'),
            'description': 'Form schema definition and versioning'
        }),
        ('Security', {
            'fields': ('public_key',),
            'description': 'Public key for widget integration (read-only)'
        }),
        ('Settings', {
            'fields': ('double_opt_enable', 'preferred_channel'),
            'description': 'Advanced form submission settings'
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    # --------------------
    # Méthodes utilitaires
    # --------------------

    def owner_email(self, obj):
        """Affiche l'email de l'owner."""
        return obj.owner.email
    owner_email.short_description = 'Owner'
    owner_email.admin_order_field = 'owner__email'

    def public_key_short(self, obj):
        """Affiche une version courte de la public_key avec survol complet."""
        key = str(obj.public_key)
        return format_html(
            '<code title="{}">{}</code>',
            key,
            f"{key[:8]}...{key[-8:]}"
        )
    public_key_short.short_description = 'Public Key'

    # --------------------
    # Actions Admin
    # --------------------

    def rotate_public_key_action(self, request, queryset):
        """
        Action admin pour régénérer les public_key.
        Affiche une page de confirmation avant rotation.
        """
        if request.POST.get('post') == 'yes':
            count = 0
            for obj in queryset:
                obj.rotate_public_key()
                obj.save()
                count += 1
                logger.info(f"Public key rotated for FormSchema id={obj.id}")

            self.message_user(
                request,
                f"Successfully rotated public_key for {count} schema(s). "
                f"⚠️ Update router integration with new keys!"
            )
            return None

        # Page de confirmation
        context = {
            'title': 'Rotate Public Keys',
            'queryset': queryset,
            'action_checkbox_name': helpers.ACTION_CHECKBOX_NAME,
            'opts': self.model._meta,
        }
        return TemplateResponse(
            request,
            'admin/core_data/rotate_public_key_confirmation.html',
            context
        )

    rotate_public_key_action.short_description = '🔄 Rotate public_key (requires router update)'


# ================================
# ADMIN : OwnerClient
# ================================

@admin.register(OwnerClient)
class OwnerClientAdmin(admin.ModelAdmin):
    """
    Administration des leads collectés.
    Permet de visualiser les informations clients,
    leur état de vérification, visites et métadonnées.
    """

    list_display = (
        'mac_address',
        'email',
        'phone',
        'owner__profile',
        'is_verified_badge',
        'visit_info',
        'created_at'
    )
    search_fields = (
        'mac_address',
        'email',
        'phone',
        'owner__profile',
    )
    list_filter = ('owner', 'is_verified',  'created_at', 'last_seen')
    readonly_fields = ('created_at', 'is_verified','last_seen', 'client_token')
    date_hierarchy = 'created_at'
    actions = ['mark_verified_action', 'export_csv_action']

    fieldsets = (
        ('Owner', {
            'fields': ('owner',)
        }),
        ('Client Info', {
            'fields': ('mac_address', 'email', 'phone')
        }),
        ('Data', {
            'fields': ('payload',),
            'description': 'Raw form data submitted by the client'
        }),
        ('Recognition', {
            'fields': ('client_token',),
            'classes': ('collapse',),
            'description': 'Internal token for client recognition'
        }),
        ('Verification & Settings', {
            'fields': ('is_verified',),
            'description': 'Lead verification and submission settings'
        }),
        ('Timestamps', {
            'fields': ('created_at', 'last_seen'),
            'classes': ('collapse',)
        }),
    )

    # --------------------
    # Méthodes utilitaires
    # --------------------

    def owner_email(self, obj):
        """Affiche l'email de l'owner."""
        return obj.owner.email
    owner_email.short_description = 'Owner'
    owner_email.admin_order_field = 'owner__email'

    def visit_info(self, obj):
        """
        Affiche les infos de visite avec date première et dernière visite.
        """
        return format_html(
            '<span title="First: {} | Last: {}">First visit</span>',
            obj.created_at.strftime('%Y-%m-%d %H:%M'),
            obj.last_seen.strftime('%Y-%m-%d %H:%M')
        )
    visit_info.short_description = 'Visits'

    def is_verified_badge(self, obj):
        """Affiche un badge coloré pour le statut de vérification."""
        color = 'green' if obj.is_verified else 'red'
        return format_html('<span style="color:{}; font-weight:bold;">{}</span>', color, obj.is_verified)
    is_verified_badge.short_description = 'Verified'

    def payload_short(self, obj):
        """Affiche un aperçu limité du payload pour éviter de surcharger la page."""
        p = str(obj.payload)
        return format_html(
            '<pre style="max-height:50px; overflow:auto">{}</pre>',
            p[:200] + ('...' if len(p) > 200 else '')
        )
    payload_short.short_description = 'Payload'

    # --------------------
    # Permissions
    # --------------------

    def has_add_permission(self, request):
        """Empêche la création manuelle de leads depuis l'admin."""
        return False

    def has_delete_permission(self, request, obj=None):
        """Empêche la suppression depuis l'admin pour sécuriser les données."""
        return False

    # --------------------
    # Actions Admin
    # --------------------

    def mark_verified_action(self, request, queryset):
        """Marque les leads sélectionnés comme vérifiés."""
        updated = queryset.update(is_verified=True)
        self.message_user(request, f"{updated} lead(s) marked as verified.")
    mark_verified_action.short_description = "✅ Mark selected leads as verified"

    def export_csv_action(self, request, queryset):
        """Exporte les leads sélectionnés en CSV."""
        meta = self.model._meta
        field_names = [field.name for field in meta.fields]

        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename={meta}.csv'

        writer = csv.writer(response)
        writer.writerow(field_names)
        for obj in queryset:
            writer.writerow([getattr(obj, field) for field in field_names])

        return response
    export_csv_action.short_description = "📄 Export selected leads to CSV"
