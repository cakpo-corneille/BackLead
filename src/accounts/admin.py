from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth import get_user_model
from django.utils.safestring import mark_safe

from core_data.models import OwnerClient

from .models import OwnerProfile
from .forms import CustomUserCreationForm, CustomUserChangeForm

User = get_user_model()


class OwnerProfileInline(admin.StackedInline):
    """Inline pour afficher le profil dans l'admin User."""
    model = OwnerProfile
    can_delete = False
    verbose_name_plural = 'Profil Propriétaire'
    classes = ('collapse',)  # Collapse par défaut
    
    readonly_fields = ('is_complete',)
    
    fieldsets = (
        ('Entreprise', {
            'fields': ('business_name', 'logo')
        }),
        ('Contact', {
            'fields': ('nom', 'prenom', 'phone_contact', 'whatsapp_contact')
        }),
        ('Localisation', {
            'fields': ('pays', 'ville', 'quartier')
        }),
        ('Objectif', {
            'fields': ('main_goal',)
        }),
        ('Statut', {
            'fields': ('is_complete',),
        }),
    )


@admin.register(User)
class CustomUserAdmin(BaseUserAdmin):
    """Admin pour le modèle User personnalisé."""
    
    form = CustomUserChangeForm
    add_form = CustomUserCreationForm
    
    list_display = ('email', 'verified_badge', 'profile_status', 'is_active', 'is_staff', 'date_joined')
    list_filter = ('is_verify', 'is_staff', 'is_active', 'date_joined')
    search_fields = ('email',)
    ordering = ('-date_joined',)
    
    actions = ['mark_as_verified', 'mark_as_unverified']
    
    fieldsets = (
        ('Authentification', {
            'fields': ('email', 'password')
        }),
        ('Vérification Email', {
            'fields': ('is_verify',)
        }),
        ('Permissions', {
            'fields': ('is_active', 'is_staff', 'is_superuser'),
            'classes': ('collapse',)
        }),
        ('Groupes & Permissions avancées', {
            'fields': ('groups', 'user_permissions'),
            'classes': ('collapse',)
        }),
        ('Dates', {
            'fields': ('date_joined', 'last_login'),
            'classes': ('collapse',)
        }),
    )

    add_fieldsets = (
        ('Créer un utilisateur', {
            'fields': ('email', 'password1', 'password2'),
        }),
    )
    
    readonly_fields = ('date_joined', 'last_login')
    inlines = (OwnerProfileInline,)
    
    def verified_badge(self, obj):
        """Badge de vérification email."""
        if obj.is_verify:
            return mark_safe('<span style="color: green;">✓ Vérifié</span>')
        return mark_safe('<span style="color: red;">✗ Non vérifié</span>')
    verified_badge.short_description = 'Email'
    
    def profile_status(self, obj):
        """Statut du profil (complet ou non)."""
        if hasattr(obj, 'profile'):
            if obj.profile.is_complete:
                return mark_safe('<span style="color: green;">✓ Complet</span>')
            return mark_safe('<span style="color: orange;">○ Incomplet</span>')
        return mark_safe('<span style="color: gray;">- Aucun</span>')
    profile_status.short_description = 'Profil'
    
    @admin.action(description='✓ Marquer comme vérifié')
    def mark_as_verified(self, request, queryset):
        """Action pour marquer les users comme vérifiés."""
        updated = queryset.update(is_verify=True)
        self.message_user(request, f'{updated} utilisateur(s) marqué(s) comme vérifié(s).')
    
    @admin.action(description='✗ Marquer comme non vérifié')
    def mark_as_unverified(self, request, queryset):
        """Action pour retirer la vérification."""
        updated = queryset.update(is_verify=False)
        self.message_user(request, f'{updated} utilisateur(s) marqué(s) comme non vérifié(s).')


@admin.register(OwnerProfile)
class OwnerProfileAdmin(admin.ModelAdmin):
    """Admin pour le modèle OwnerProfile."""
    
    list_display = (
        'logo_thumbnail',
        'business_name',
        'owner_email',
        'completion_badge',
        'goal_display',
        'location_display',
        'total_clients',
        'verified_clients',
    )
    list_filter = ('is_complete', 'main_goal', 'pays', 'ville')
    search_fields = ('business_name', 'nom', 'prenom', 'user__email', 'ville', 'quartier')
    ordering = ('-user__date_joined',)
    
    readonly_fields = ('is_complete', 'user')
    
    fieldsets = (
        ('Utilisateur', {
            'fields': ('user',)
        }),
        ('Entreprise', {
            'fields': ('business_name', 'logo')
        }),
        ('Identité', {
            'fields': ('nom', 'prenom')
        }),
        ('Contact', {
            'fields': ('phone_contact', 'whatsapp_contact')
        }),
        ('Localisation', {
            'fields': ('pays', 'ville', 'quartier')
        }),
        ('Objectif', {
            'fields': ('main_goal',)
        }),
        ('Statut (auto)', {
            'fields': ('is_complete',),
            'classes': ('collapse',),
            'description': 'Calculé automatiquement - Ne peut pas être modifié manuellement'
        }),
    )
    
    def logo_thumbnail(self, obj):
        """Miniature du logo."""
        if obj.logo:
            return mark_safe(
                f'<img src="{obj.logo.url}" '
                f'style="width: 50px; height: 50px; object-fit: cover; border-radius: 5px;" />'
            )
        return mark_safe('<span style="color: gray;">Aucun</span>')
    logo_thumbnail.short_description = 'Logo'
    
    def owner_email(self, obj):
        """Email du propriétaire."""
        return obj.user.email
    owner_email.short_description = 'Email'
    owner_email.admin_order_field = 'user__email'
    
    def completion_badge(self, obj):
        """Badge de statut de complétion."""
        if obj.is_complete:
            return mark_safe(
                '<span style="background: #28a745; color: white; padding: 3px 8px; '
                'border-radius: 3px; font-size: 11px;">✓ COMPLET</span>'
            )
        return mark_safe(
            '<span style="background: #ffc107; color: black; padding: 3px 8px; '
            'border-radius: 3px; font-size: 11px;">○ INCOMPLET</span>'
        )
    completion_badge.short_description = 'Statut'
    
    def goal_display(self, obj):
        """Affichage formaté de l'objectif."""
        if obj.main_goal:
            return obj.get_main_goal_display()
        return '-'
    goal_display.short_description = 'Objectif'
    
    def location_display(self, obj):
        """Localisation formatée."""
        parts = filter(None, [obj.quartier, obj.ville, obj.pays])
        return ', '.join(parts) or '-'
    location_display.short_description = 'Localisation'
    
    def has_add_permission(self, request):
        """Empêche la création manuelle (créé automatiquement par signal)."""
        return False

    def has_delete_permission(self, request, obj=None):
        """Seuls les superutilisateurs peuvent supprimer un profil."""
        return request.user.is_superuser

    def total_clients(self, obj):
        """Nombre total de clients liés à ce propriétaire."""
        return OwnerClient.objects.filter(owner=obj.user).count()
    total_clients.short_description = "Clients"

    def verified_clients(self, obj):
        """Nombre de clients vérifiés associés à ce propriétaire."""
        return OwnerClient.objects.filter(owner=obj.user, is_verified=True).count()
    verified_clients.short_description = "vérifiés"
