from rest_framework import serializers
from .models import FeatureFlag, SystemConfig, AuditLog, DailyMetrics, AlertRule


class FeatureFlagSerializer(serializers.ModelSerializer):
    """Serializer pour les feature flags"""
    enabled_plans_count = serializers.SerializerMethodField()
    enabled_owners_count = serializers.SerializerMethodField()
    
    class Meta:
        model = FeatureFlag
        fields = [
            'id', 'key', 'name', 'description',
            'is_enabled', 'rollout_percentage',
            'enabled_plans_count', 'enabled_owners_count',
            'metadata', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']
    
    def get_enabled_plans_count(self, obj) -> int:
        return obj.enabled_for_plans.count()
    
    def get_enabled_owners_count(self, obj) -> int:
        return obj.enabled_for_owners.count()


class FeatureFlagDetailSerializer(FeatureFlagSerializer):
    """Serializer detaille avec les plans et owners"""
    enabled_for_plans = serializers.SerializerMethodField()
    enabled_for_owners = serializers.SerializerMethodField()
    
    class Meta(FeatureFlagSerializer.Meta):
        fields = FeatureFlagSerializer.Meta.fields + ['enabled_for_plans', 'enabled_for_owners']
    
    def get_enabled_for_plans(self, obj) -> list:
        return list(obj.enabled_for_plans.values('id', 'name', 'slug'))
    
    def get_enabled_for_owners(self, obj) -> list:
        return list(obj.enabled_for_owners.values('id', 'business_name', 'user__email'))


class FeatureFlagCreateSerializer(serializers.ModelSerializer):
    """Serializer pour creer/modifier un feature flag"""
    enabled_for_plans = serializers.PrimaryKeyRelatedField(
        many=True,
        required=False,
        queryset=None
    )
    enabled_for_owners = serializers.PrimaryKeyRelatedField(
        many=True,
        required=False,
        queryset=None
    )
    
    class Meta:
        model = FeatureFlag
        fields = [
            'key', 'name', 'description',
            'is_enabled', 'rollout_percentage',
            'enabled_for_plans', 'enabled_for_owners',
            'metadata'
        ]
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from subscriptions.models import Plan
        from accounts.models import Owner
        self.fields['enabled_for_plans'].queryset = Plan.objects.all()
        self.fields['enabled_for_owners'].queryset = Owner.objects.all()
    
    def validate_rollout_percentage(self, value):
        if value < 0 or value > 100:
            raise serializers.ValidationError("Le pourcentage doit etre entre 0 et 100.")
        return value


class SystemConfigSerializer(serializers.ModelSerializer):
    """Serializer pour les configurations systeme"""
    updated_by_email = serializers.CharField(source='updated_by.email', read_only=True)
    
    class Meta:
        model = SystemConfig
        fields = [
            'id', 'key', 'value', 'value_type',
            'description', 'updated_at', 'updated_by_email'
        ]
        read_only_fields = ['id', 'updated_at', 'updated_by_email']


class AuditLogSerializer(serializers.ModelSerializer):
    """Serializer pour les logs d'audit"""
    admin_email = serializers.CharField(source='admin.email', read_only=True)
    action_display = serializers.CharField(source='get_action_display', read_only=True)
    
    class Meta:
        model = AuditLog
        fields = [
            'id', 'admin_email', 'action', 'action_display',
            'target_repr', 'details',
            'ip_address', 'created_at'
        ]


class DailyMetricsSerializer(serializers.ModelSerializer):
    """Serializer pour les metriques journalieres"""
    
    class Meta:
        model = DailyMetrics
        fields = '__all__'


class AlertRuleSerializer(serializers.ModelSerializer):
    """Serializer pour les regles d'alerte"""
    metric_display = serializers.CharField(source='get_metric_display', read_only=True)
    operator_display = serializers.CharField(source='get_operator_display', read_only=True)
    
    class Meta:
        model = AlertRule
        fields = [
            'id', 'name', 'metric', 'metric_display',
            'operator', 'operator_display', 'threshold',
            'notify_email', 'notify_webhook',
            'is_active', 'last_triggered',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'last_triggered', 'created_at', 'updated_at']


# === Serializers pour les owners (gestion superadmin) ===

class OwnerListSerializer(serializers.Serializer):
    """Serializer pour la liste des owners (superadmin)"""
    id = serializers.IntegerField()
    email = serializers.CharField(source='user.email')
    business_name = serializers.CharField()
    phone = serializers.CharField()
    is_active = serializers.BooleanField(source='user.is_active')
    created_at = serializers.DateTimeField()
    
    # Subscription info
    subscription_status = serializers.SerializerMethodField()
    subscription_plan = serializers.SerializerMethodField()
    
    # Usage
    leads_count = serializers.SerializerMethodField()
    widgets_count = serializers.SerializerMethodField()
    
    def get_subscription_status(self, obj) -> str:
        sub = getattr(obj, 'subscription', None)
        return sub.status if sub else 'none'
    
    def get_subscription_plan(self, obj) -> str:
        sub = getattr(obj, 'subscription', None)
        return sub.plan.name if sub else 'N/A'
    
    def get_leads_count(self, obj) -> int:
        return getattr(obj, 'leads_count', 0)
    
    def get_widgets_count(self, obj) -> int:
        return getattr(obj, 'widgets_count', 0)


class OwnerDetailSerializer(OwnerListSerializer):
    """Serializer detaille pour un owner (superadmin)"""
    last_login = serializers.DateTimeField(source='user.last_login')
    date_joined = serializers.DateTimeField(source='user.date_joined')
    
    # Subscription complete
    subscription = serializers.SerializerMethodField()
    
    # Usage detaille
    recent_leads = serializers.SerializerMethodField()
    recent_payments = serializers.SerializerMethodField()
    
    def get_subscription(self, obj):
        from subscriptions.serializers import SubscriptionSerializer
        sub = getattr(obj, 'subscription', None)
        if sub:
            return SubscriptionSerializer(sub).data
        return None
    
    def get_recent_leads(self, obj) -> list:
        from core_data.models import Lead
        leads = Lead.objects.filter(owner=obj).order_by('-created_at')[:5]
        return [
            {'id': l.id, 'email': l.email, 'created_at': l.created_at}
            for l in leads
        ]
    
    def get_recent_payments(self, obj) -> list:
        from subscriptions.models import Payment
        sub = getattr(obj, 'subscription', None)
        if not sub:
            return []
        payments = sub.payments.order_by('-created_at')[:5]
        return [
            {
                'id': p.id,
                'amount': str(p.amount),
                'status': p.status,
                'created_at': p.created_at
            }
            for p in payments
        ]


class SuspendOwnerSerializer(serializers.Serializer):
    """Serializer pour suspendre un owner"""
    reason = serializers.CharField(max_length=500, required=False, allow_blank=True)


class ExtendSubscriptionSerializer(serializers.Serializer):
    """Serializer pour prolonger un abonnement"""
    days = serializers.IntegerField(min_value=1, max_value=365)
    reason = serializers.CharField(max_length=500, required=False, allow_blank=True)


class UpgradeSubscriptionAdminSerializer(serializers.Serializer):
    """Serializer pour upgrade force par admin"""
    plan_id = serializers.IntegerField()
    reason = serializers.CharField(max_length=500, required=False, allow_blank=True)
