from rest_framework import serializers
from .models import Plan, Subscription, Payment, Invoice


class PlanSerializer(serializers.ModelSerializer):
    """Serializer pour les plans d'abonnement"""
    
    class Meta:
        model = Plan
        fields = [
            'id', 'name', 'slug', 'description',
            'price_monthly', 'price_yearly', 'currency',
            'max_widgets', 'max_leads_per_month', 'max_routers',
            'features', 'trial_days', 'is_popular', 'display_order'
        ]
        read_only_fields = ['id']


class PlanSummarySerializer(serializers.ModelSerializer):
    """Serializer resume pour les plans (dans les listes)"""
    
    class Meta:
        model = Plan
        fields = ['id', 'name', 'slug', 'price_monthly', 'price_yearly', 'currency']


class SubscriptionSerializer(serializers.ModelSerializer):
    """Serializer complet pour les abonnements"""
    plan = PlanSerializer(read_only=True)
    plan_id = serializers.PrimaryKeyRelatedField(
        queryset=Plan.objects.filter(is_active=True),
        write_only=True,
        source='plan'
    )
    owner_email = serializers.CharField(source='owner.user.email', read_only=True)
    owner_business = serializers.CharField(source='owner.business_name', read_only=True)
    days_until_renewal = serializers.SerializerMethodField()
    current_price = serializers.SerializerMethodField()
    usage_percentage = serializers.SerializerMethodField()
    
    class Meta:
        model = Subscription
        fields = [
            'id', 'owner_email', 'owner_business', 'plan', 'plan_id',
            'status', 'billing_cycle',
            'trial_start', 'trial_end',
            'current_period_start', 'current_period_end',
            'cancelled_at', 'cancel_reason',
            'leads_used', 'days_until_renewal', 'current_price', 'usage_percentage',
            'created_at', 'updated_at'
        ]
        read_only_fields = [
            'id', 'trial_start', 'trial_end',
            'current_period_start', 'current_period_end',
            'cancelled_at', 'leads_used', 'created_at', 'updated_at'
        ]
    
    def get_days_until_renewal(self, obj) -> int:
        return obj.days_until_renewal()
    
    def get_current_price(self, obj) -> str:
        return str(obj.get_current_price())
    
    def get_usage_percentage(self, obj) -> float:
        if obj.plan.max_leads_per_month == 0:
            return 0
        return round((obj.leads_used / obj.plan.max_leads_per_month) * 100, 1)


class SubscriptionSummarySerializer(serializers.ModelSerializer):
    """Serializer resume pour l'abonnement (dashboard owner)"""
    plan_name = serializers.CharField(source='plan.name', read_only=True)
    plan_slug = serializers.CharField(source='plan.slug', read_only=True)
    days_until_renewal = serializers.SerializerMethodField()
    can_create_lead = serializers.SerializerMethodField()
    leads_remaining = serializers.SerializerMethodField()
    
    class Meta:
        model = Subscription
        fields = [
            'status', 'plan_name', 'plan_slug', 'billing_cycle',
            'current_period_end', 'days_until_renewal',
            'leads_used', 'leads_remaining', 'can_create_lead'
        ]
    
    def get_days_until_renewal(self, obj) -> int:
        return obj.days_until_renewal()
    
    def get_can_create_lead(self, obj) -> bool:
        return obj.can_create_lead()
    
    def get_leads_remaining(self, obj) -> int:
        return max(0, obj.plan.max_leads_per_month - obj.leads_used)


class UpgradeSubscriptionSerializer(serializers.Serializer):
    """Serializer pour upgrade/downgrade de plan"""
    plan_id = serializers.PrimaryKeyRelatedField(
        queryset=Plan.objects.filter(is_active=True)
    )
    billing_cycle = serializers.ChoiceField(
        choices=Subscription.BillingCycle.choices,
        required=False
    )
    
    def validate_plan_id(self, value):
        subscription = self.context.get('subscription')
        if subscription and subscription.plan == value:
            raise serializers.ValidationError("Vous etes deja sur ce plan.")
        return value


class CancelSubscriptionSerializer(serializers.Serializer):
    """Serializer pour annulation d'abonnement"""
    reason = serializers.CharField(max_length=500, required=False, allow_blank=True)
    confirm = serializers.BooleanField()
    
    def validate_confirm(self, value):
        if not value:
            raise serializers.ValidationError("Vous devez confirmer l'annulation.")
        return value


class InitiatePaymentSerializer(serializers.Serializer):
    """Serializer pour initier un paiement Mobile Money"""
    provider = serializers.ChoiceField(choices=[
        ('mtn_momo', 'MTN Mobile Money'),
        ('moov_money', 'Moov Money'),
    ])
    phone_number = serializers.CharField(max_length=20)
    plan_id = serializers.PrimaryKeyRelatedField(
        queryset=Plan.objects.filter(is_active=True),
        required=False,
        help_text="Requis pour upgrade, sinon utilise le plan actuel"
    )
    billing_cycle = serializers.ChoiceField(
        choices=Subscription.BillingCycle.choices,
        default=Subscription.BillingCycle.MONTHLY
    )
    
    def validate_phone_number(self, value):
        # Nettoyer et valider le numero (format Benin: +229 XX XX XX XX)
        cleaned = ''.join(filter(str.isdigit, value))
        if len(cleaned) < 8:
            raise serializers.ValidationError("Numero de telephone invalide.")
        
        # Ajouter prefixe Benin si necessaire
        if not cleaned.startswith('229'):
            cleaned = '229' + cleaned
        
        return cleaned
    
    def validate(self, attrs):
        provider = attrs.get('provider')
        phone = attrs.get('phone_number', '')
        
        # Validation specifique par operateur
        if provider == 'mtn_momo':
            # Prefixes MTN Benin: 90, 91, 96, 97
            mtn_prefixes = ['90', '91', '96', '97']
            phone_without_country = phone[3:] if phone.startswith('229') else phone
            if not any(phone_without_country.startswith(p) for p in mtn_prefixes):
                raise serializers.ValidationError({
                    'phone_number': "Ce numero n'est pas un numero MTN valide."
                })
        
        elif provider == 'moov_money':
            # Prefixes Moov Benin: 94, 95, 98, 99
            moov_prefixes = ['94', '95', '98', '99']
            phone_without_country = phone[3:] if phone.startswith('229') else phone
            if not any(phone_without_country.startswith(p) for p in moov_prefixes):
                raise serializers.ValidationError({
                    'phone_number': "Ce numero n'est pas un numero Moov valide."
                })
        
        return attrs


class PaymentSerializer(serializers.ModelSerializer):
    """Serializer pour les paiements"""
    provider_display = serializers.CharField(source='get_provider_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    
    class Meta:
        model = Payment
        fields = [
            'id', 'uuid', 'amount', 'currency',
            'status', 'status_display', 'provider', 'provider_display',
            'phone_number', 'external_id', 'description',
            'error_message', 'created_at', 'completed_at'
        ]
        read_only_fields = fields


class PaymentDetailSerializer(PaymentSerializer):
    """Serializer detaille pour un paiement"""
    subscription_plan = serializers.CharField(source='subscription.plan.name', read_only=True)
    
    class Meta(PaymentSerializer.Meta):
        fields = PaymentSerializer.Meta.fields + ['subscription_plan', 'metadata']


class InvoiceSerializer(serializers.ModelSerializer):
    """Serializer pour les factures"""
    plan_name = serializers.CharField(source='subscription.plan.name', read_only=True)
    
    class Meta:
        model = Invoice
        fields = [
            'id', 'invoice_number', 'amount', 'currency',
            'period_start', 'period_end',
            'is_paid', 'paid_at', 'pdf_url', 'plan_name',
            'created_at'
        ]
        read_only_fields = fields


class InvoiceDetailSerializer(InvoiceSerializer):
    """Serializer detaille pour une facture"""
    payment = PaymentSerializer(read_only=True)
    
    class Meta(InvoiceSerializer.Meta):
        fields = InvoiceSerializer.Meta.fields + ['payment', 'billing_info']
