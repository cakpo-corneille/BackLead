from django.contrib import admin
from .models import FeatureFlag, SystemConfig, AuditLog, DailyMetrics, AlertRule


@admin.register(FeatureFlag)
class FeatureFlagAdmin(admin.ModelAdmin):
    list_display = ['key', 'name', 'is_enabled', 'rollout_percentage', 'updated_at']
    list_filter = ['is_enabled']
    search_fields = ['key', 'name', 'description']
    filter_horizontal = ['enabled_for_plans', 'enabled_for_owners']
    readonly_fields = ['created_at', 'updated_at']
    
    fieldsets = (
        ('Identification', {
            'fields': ('key', 'name', 'description')
        }),
        ('Activation', {
            'fields': ('is_enabled', 'rollout_percentage')
        }),
        ('Ciblage', {
            'fields': ('enabled_for_plans', 'enabled_for_owners'),
            'classes': ('collapse',)
        }),
        ('Metadata', {
            'fields': ('metadata', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


@admin.register(SystemConfig)
class SystemConfigAdmin(admin.ModelAdmin):
    list_display = ['key', 'value', 'value_type', 'updated_at', 'updated_by']
    list_filter = ['value_type']
    search_fields = ['key', 'description']
    readonly_fields = ['updated_at']
    
    def save_model(self, request, obj, form, change):
        obj.updated_by = request.user
        super().save_model(request, obj, form, change)


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ['created_at', 'admin', 'action', 'target_repr', 'ip_address']
    list_filter = ['action', 'created_at']
    search_fields = ['admin__email', 'target_repr', 'ip_address']
    readonly_fields = [
        'admin', 'action', 'target_type', 'target_id', 'target_repr',
        'details', 'ip_address', 'user_agent', 'created_at'
    ]
    date_hierarchy = 'created_at'
    
    def has_add_permission(self, request):
        return False
    
    def has_change_permission(self, request, obj=None):
        return False
    
    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser


@admin.register(DailyMetrics)
class DailyMetricsAdmin(admin.ModelAdmin):
    list_display = [
        'date', 'total_owners', 'new_owners',
        'active_subscriptions', 'mrr', 'new_leads'
    ]
    list_filter = ['date']
    date_hierarchy = 'date'
    readonly_fields = ['created_at', 'updated_at']
    
    fieldsets = (
        ('Date', {
            'fields': ('date',)
        }),
        ('Owners', {
            'fields': ('total_owners', 'new_owners', 'active_owners')
        }),
        ('Subscriptions', {
            'fields': (
                'total_subscriptions', 'trial_subscriptions',
                'active_subscriptions', 'churned_subscriptions',
                'subscriptions_by_plan'
            )
        }),
        ('Revenue', {
            'fields': ('mrr', 'arr', 'new_mrr', 'churned_mrr', 'revenue_today')
        }),
        ('Usage', {
            'fields': (
                'total_leads', 'new_leads',
                'total_widgets', 'active_widgets',
                'total_sessions', 'new_sessions', 'active_sessions'
            )
        }),
        ('Technique', {
            'fields': (
                'api_calls', 'api_errors', 'avg_response_time_ms',
                'celery_tasks_completed', 'celery_tasks_failed'
            ),
            'classes': ('collapse',)
        }),
    )


@admin.register(AlertRule)
class AlertRuleAdmin(admin.ModelAdmin):
    list_display = ['name', 'metric', 'operator', 'threshold', 'is_active', 'last_triggered']
    list_filter = ['is_active', 'metric']
    search_fields = ['name']
    readonly_fields = ['last_triggered', 'created_at', 'updated_at']
