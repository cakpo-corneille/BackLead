from django.contrib import admin
from .models import Plan, Subscription, Payment, Invoice


@admin.register(Plan)
class PlanAdmin(admin.ModelAdmin):
    list_display = ['name', 'slug', 'price_monthly', 'price_yearly', 'max_leads_per_month', 'is_active', 'is_popular']
    list_filter = ['is_active', 'is_popular']
    search_fields = ['name', 'slug']
    prepopulated_fields = {'slug': ('name',)}
    ordering = ['display_order', 'price_monthly']
    
    fieldsets = (
        ('Informations', {
            'fields': ('name', 'slug', 'description')
        }),
        ('Tarification', {
            'fields': ('price_monthly', 'price_yearly', 'currency', 'trial_days')
        }),
        ('Limites', {
            'fields': ('max_widgets', 'max_leads_per_month', 'max_routers')
        }),
        ('Fonctionnalites', {
            'fields': ('features',)
        }),
        ('Affichage', {
            'fields': ('is_active', 'is_popular', 'display_order')
        }),
    )


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = ['owner', 'plan', 'status', 'billing_cycle', 'current_period_end', 'leads_used']
    list_filter = ['status', 'billing_cycle', 'plan']
    search_fields = ['owner__user__email', 'owner__business_name']
    raw_id_fields = ['owner', 'plan']
    readonly_fields = ['created_at', 'updated_at', 'trial_start', 'trial_end']
    date_hierarchy = 'created_at'
    
    fieldsets = (
        ('Proprietaire', {
            'fields': ('owner', 'plan')
        }),
        ('Statut', {
            'fields': ('status', 'billing_cycle')
        }),
        ('Periode d\'essai', {
            'fields': ('trial_start', 'trial_end'),
            'classes': ('collapse',)
        }),
        ('Periode courante', {
            'fields': ('current_period_start', 'current_period_end')
        }),
        ('Annulation', {
            'fields': ('cancelled_at', 'cancel_reason'),
            'classes': ('collapse',)
        }),
        ('Usage', {
            'fields': ('leads_used',)
        }),
        ('Metadata', {
            'fields': ('metadata', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def get_queryset(self, request):
        return super().get_queryset(request).select_related('owner__user', 'plan')


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ['id', 'subscription', 'amount', 'currency', 'provider', 'status', 'phone_number', 'created_at']
    list_filter = ['status', 'provider', 'created_at']
    search_fields = ['subscription__owner__user__email', 'phone_number', 'external_id']
    raw_id_fields = ['subscription']
    readonly_fields = ['uuid', 'created_at', 'updated_at', 'completed_at']
    date_hierarchy = 'created_at'
    
    fieldsets = (
        ('Transaction', {
            'fields': ('uuid', 'subscription', 'amount', 'currency', 'description')
        }),
        ('Mobile Money', {
            'fields': ('provider', 'phone_number', 'external_id', 'external_reference')
        }),
        ('Statut', {
            'fields': ('status', 'error_message')
        }),
        ('Dates', {
            'fields': ('created_at', 'updated_at', 'completed_at')
        }),
        ('Metadata', {
            'fields': ('metadata',),
            'classes': ('collapse',)
        }),
    )
    
    def get_queryset(self, request):
        return super().get_queryset(request).select_related('subscription__owner__user')


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = ['invoice_number', 'subscription', 'amount', 'currency', 'is_paid', 'period_start', 'period_end']
    list_filter = ['is_paid', 'created_at']
    search_fields = ['invoice_number', 'subscription__owner__user__email']
    raw_id_fields = ['subscription', 'payment']
    readonly_fields = ['invoice_number', 'created_at', 'updated_at']
    date_hierarchy = 'created_at'
    
    def get_queryset(self, request):
        return super().get_queryset(request).select_related('subscription__owner__user', 'payment')
