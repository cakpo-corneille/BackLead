import logging
from rest_framework import viewsets, status, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView
from django.shortcuts import get_object_or_404
from django.db.models import Count, Q
from django.utils import timezone
from datetime import timedelta

from .models import FeatureFlag, SystemConfig, AuditLog, DailyMetrics, AlertRule
from .serializers import (
    FeatureFlagSerializer, FeatureFlagDetailSerializer, FeatureFlagCreateSerializer,
    SystemConfigSerializer, AuditLogSerializer, DailyMetricsSerializer,
    AlertRuleSerializer, OwnerListSerializer, OwnerDetailSerializer,
    SuspendOwnerSerializer, ExtendSubscriptionSerializer, UpgradeSubscriptionAdminSerializer
)
from .services import KPIService, OwnerManagementService
from .permissions import IsSuperAdmin, CanImpersonate

logger = logging.getLogger(__name__)


# === KPIs Views ===

class RealtimeKPIsView(APIView):
    """
    GET /api/v1/superadmin/kpis/realtime/
    
    Retourne les KPIs temps reel du SaaS.
    """
    permission_classes = [IsSuperAdmin]
    
    def get(self, request):
        use_cache = request.query_params.get('refresh') != 'true'
        kpis = KPIService.get_realtime_kpis(use_cache=use_cache)
        return Response(kpis)


class RevenueKPIsView(APIView):
    """
    GET /api/v1/superadmin/kpis/revenue/
    
    Retourne les details de revenue (MRR, ARR, LTV, breakdown par plan).
    """
    permission_classes = [IsSuperAdmin]
    
    def get(self, request):
        data = {
            'revenue': KPIService._get_revenue_metrics(),
            'breakdown': KPIService.get_revenue_breakdown(),
            'churn_rate_30d': KPIService.calculate_churn_rate(30),
            'ltv': float(KPIService.calculate_ltv()),
        }
        return Response(data)


class HistoricalKPIsView(APIView):
    """
    GET /api/v1/superadmin/kpis/history/
    
    Retourne l'historique des metriques pour les graphiques.
    """
    permission_classes = [IsSuperAdmin]
    
    def get(self, request):
        days = int(request.query_params.get('days', 30))
        days = min(days, 365)  # Max 1 an
        
        metrics = KPIService.get_historical_metrics(days)
        return Response({
            'period_days': days,
            'data': metrics
        })


class SystemHealthView(APIView):
    """
    GET /api/v1/superadmin/health/
    
    Retourne l'etat de sante du systeme.
    """
    permission_classes = [IsSuperAdmin]
    
    def get(self, request):
        use_cache = request.query_params.get('refresh') != 'true'
        health = KPIService.get_system_health(use_cache=use_cache)
        return Response(health)


# === Owner Management Views ===

class OwnerManagementViewSet(viewsets.GenericViewSet):
    """
    API de gestion des owners pour le superadmin.
    
    GET /api/v1/superadmin/owners/ - Liste des owners
    GET /api/v1/superadmin/owners/{id}/ - Detail owner
    POST /api/v1/superadmin/owners/{id}/suspend/ - Suspendre
    POST /api/v1/superadmin/owners/{id}/activate/ - Reactiver
    POST /api/v1/superadmin/owners/{id}/reset-password/ - Reset password
    POST /api/v1/superadmin/owners/{id}/impersonate/ - Se connecter en tant que
    """
    permission_classes = [IsSuperAdmin]
    
    def get_queryset(self):
        from accounts.models import Owner
        return Owner.objects.select_related(
            'user', 'subscription', 'subscription__plan'
        ).annotate(
            leads_count=Count('leads'),
            widgets_count=Count('widgets')
        )
    
    def get_serializer_class(self):
        if self.action == 'retrieve':
            return OwnerDetailSerializer
        return OwnerListSerializer
    
    def list(self, request):
        """Liste des owners avec filtres"""
        queryset = self.get_queryset()
        
        # Filtres
        search = request.query_params.get('search')
        if search:
            queryset = queryset.filter(
                Q(user__email__icontains=search) |
                Q(business_name__icontains=search) |
                Q(phone__icontains=search)
            )
        
        status_filter = request.query_params.get('status')
        if status_filter == 'active':
            queryset = queryset.filter(user__is_active=True)
        elif status_filter == 'suspended':
            queryset = queryset.filter(user__is_active=False)
        
        subscription_status = request.query_params.get('subscription')
        if subscription_status:
            queryset = queryset.filter(subscription__status=subscription_status)
        
        plan = request.query_params.get('plan')
        if plan:
            queryset = queryset.filter(subscription__plan__slug=plan)
        
        # Tri
        ordering = request.query_params.get('ordering', '-created_at')
        queryset = queryset.order_by(ordering)
        
        # Pagination simple
        page_size = int(request.query_params.get('page_size', 20))
        page = int(request.query_params.get('page', 1))
        start = (page - 1) * page_size
        end = start + page_size
        
        total = queryset.count()
        owners = queryset[start:end]
        
        serializer = self.get_serializer(owners, many=True)
        
        return Response({
            'count': total,
            'page': page,
            'page_size': page_size,
            'results': serializer.data
        })
    
    def retrieve(self, request, pk=None):
        """Detail d'un owner"""
        owner = get_object_or_404(self.get_queryset(), pk=pk)
        
        # Log consultation
        AuditLog.log(
            admin=request.user,
            action=AuditLog.Action.OWNER_VIEWED,
            target=owner,
            request=request
        )
        
        serializer = OwnerDetailSerializer(owner)
        return Response(serializer.data)
    
    @action(detail=True, methods=['post'])
    def suspend(self, request, pk=None):
        """Suspend un owner"""
        owner = get_object_or_404(self.get_queryset(), pk=pk)
        
        if not owner.user.is_active:
            return Response(
                {'detail': 'Cet owner est deja suspendu.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        serializer = SuspendOwnerSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        reason = serializer.validated_data.get('reason', '')
        OwnerManagementService.suspend_owner(owner, request.user, reason, request)
        
        return Response({'detail': f'Owner {owner.business_name} suspendu.'})
    
    @action(detail=True, methods=['post'])
    def activate(self, request, pk=None):
        """Reactive un owner"""
        owner = get_object_or_404(self.get_queryset(), pk=pk)
        
        if owner.user.is_active:
            return Response(
                {'detail': 'Cet owner est deja actif.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        OwnerManagementService.activate_owner(owner, request.user, request)
        
        return Response({'detail': f'Owner {owner.business_name} reactive.'})
    
    @action(detail=True, methods=['post'], url_path='reset-password')
    def reset_password(self, request, pk=None):
        """Envoie un email de reset password"""
        owner = get_object_or_404(self.get_queryset(), pk=pk)
        
        OwnerManagementService.reset_owner_password(owner, request.user, request)
        
        return Response({
            'detail': f'Email de reinitialisation envoye a {owner.user.email}.'
        })
    
    @action(detail=True, methods=['post'], permission_classes=[CanImpersonate])
    def impersonate(self, request, pk=None):
        """Genere un token pour se connecter en tant que l'owner"""
        owner = get_object_or_404(self.get_queryset(), pk=pk)
        
        # Verification supplementaire
        if owner.user.is_superuser:
            return Response(
                {'detail': 'Impossible d\'impersonner un superadmin.'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        tokens = OwnerManagementService.generate_impersonation_token(
            owner, request.user, request
        )
        
        return Response({
            'detail': f'Token d\'impersonation genere pour {owner.business_name}.',
            'warning': 'Ce token expire dans 1 heure. Utilisez-le avec precaution.',
            'tokens': tokens
        })


# === Subscription Management Views ===

class SubscriptionManagementViewSet(viewsets.GenericViewSet):
    """
    API de gestion des abonnements pour le superadmin.
    
    GET /api/v1/superadmin/subscriptions/ - Liste des abonnements
    POST /api/v1/superadmin/subscriptions/{id}/extend/ - Prolonger
    POST /api/v1/superadmin/subscriptions/{id}/upgrade/ - Upgrade force
    """
    permission_classes = [IsSuperAdmin]
    
    def get_queryset(self):
        from subscriptions.models import Subscription
        return Subscription.objects.select_related('owner__user', 'plan')
    
    def list(self, request):
        """Liste des abonnements"""
        from subscriptions.serializers import SubscriptionSerializer
        
        queryset = self.get_queryset()
        
        # Filtres
        status_filter = request.query_params.get('status')
        if status_filter:
            queryset = queryset.filter(status=status_filter)
        
        plan = request.query_params.get('plan')
        if plan:
            queryset = queryset.filter(plan__slug=plan)
        
        # Expiring soon
        expiring = request.query_params.get('expiring')
        if expiring == 'true':
            soon = timezone.now() + timedelta(days=7)
            queryset = queryset.filter(
                current_period_end__lte=soon,
                status='active'
            )
        
        queryset = queryset.order_by('-created_at')[:100]
        serializer = SubscriptionSerializer(queryset, many=True)
        
        return Response(serializer.data)
    
    @action(detail=True, methods=['post'])
    def extend(self, request, pk=None):
        """Prolonge un abonnement manuellement"""
        subscription = get_object_or_404(self.get_queryset(), pk=pk)
        
        serializer = ExtendSubscriptionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        days = serializer.validated_data['days']
        reason = serializer.validated_data.get('reason', '')
        
        # Prolonger
        subscription.current_period_end += timedelta(days=days)
        subscription.save()
        
        # Log
        AuditLog.log(
            admin=request.user,
            action=AuditLog.Action.SUBSCRIPTION_EXTENDED,
            target=subscription,
            details={'days_added': days, 'reason': reason},
            request=request
        )
        
        return Response({
            'detail': f'Abonnement prolonge de {days} jours.',
            'new_period_end': subscription.current_period_end
        })
    
    @action(detail=True, methods=['post'])
    def upgrade(self, request, pk=None):
        """Upgrade force un abonnement"""
        from subscriptions.models import Plan
        from subscriptions.services import SubscriptionService
        
        subscription = get_object_or_404(self.get_queryset(), pk=pk)
        
        serializer = UpgradeSubscriptionAdminSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        plan = get_object_or_404(Plan, pk=serializer.validated_data['plan_id'])
        reason = serializer.validated_data.get('reason', '')
        
        old_plan = subscription.plan
        SubscriptionService.upgrade_plan(subscription, plan)
        
        # Log
        AuditLog.log(
            admin=request.user,
            action=AuditLog.Action.SUBSCRIPTION_UPGRADED,
            target=subscription,
            details={
                'old_plan': old_plan.name,
                'new_plan': plan.name,
                'reason': reason
            },
            request=request
        )
        
        return Response({
            'detail': f'Abonnement upgrade de {old_plan.name} vers {plan.name}.'
        })


# === Feature Flags Views ===

class FeatureFlagViewSet(viewsets.ModelViewSet):
    """
    CRUD pour les feature flags.
    
    GET /api/v1/superadmin/flags/ - Liste
    POST /api/v1/superadmin/flags/ - Creer
    GET /api/v1/superadmin/flags/{key}/ - Detail
    PUT /api/v1/superadmin/flags/{key}/ - Modifier
    DELETE /api/v1/superadmin/flags/{key}/ - Supprimer
    POST /api/v1/superadmin/flags/{key}/toggle/ - Activer/Desactiver
    """
    permission_classes = [IsSuperAdmin]
    queryset = FeatureFlag.objects.all()
    lookup_field = 'key'
    
    def get_serializer_class(self):
        if self.action == 'retrieve':
            return FeatureFlagDetailSerializer
        if self.action in ['create', 'update', 'partial_update']:
            return FeatureFlagCreateSerializer
        return FeatureFlagSerializer
    
    def perform_create(self, serializer):
        flag = serializer.save()
        AuditLog.log(
            admin=self.request.user,
            action=AuditLog.Action.FLAG_CREATED,
            target=flag,
            details={'key': flag.key},
            request=self.request
        )
    
    def perform_update(self, serializer):
        flag = serializer.save()
        AuditLog.log(
            admin=self.request.user,
            action=AuditLog.Action.FLAG_UPDATED,
            target=flag,
            details={'key': flag.key},
            request=self.request
        )
    
    def perform_destroy(self, instance):
        key = instance.key
        instance.delete()
        AuditLog.log(
            admin=self.request.user,
            action=AuditLog.Action.FLAG_DELETED,
            target=None,
            details={'key': key},
            request=self.request
        )
    
    @action(detail=True, methods=['post'])
    def toggle(self, request, key=None):
        """Toggle on/off un flag"""
        flag = self.get_object()
        flag.is_enabled = not flag.is_enabled
        flag.save()
        
        AuditLog.log(
            admin=request.user,
            action=AuditLog.Action.FLAG_TOGGLED,
            target=flag,
            details={'new_state': flag.is_enabled},
            request=request
        )
        
        return Response({
            'key': flag.key,
            'is_enabled': flag.is_enabled,
            'message': f'Flag {"active" if flag.is_enabled else "desactive"}'
        })


# === System Config Views ===

class SystemConfigViewSet(viewsets.ModelViewSet):
    """
    CRUD pour la configuration systeme.
    """
    permission_classes = [IsSuperAdmin]
    queryset = SystemConfig.objects.all()
    serializer_class = SystemConfigSerializer
    lookup_field = 'key'
    
    def perform_update(self, serializer):
        config = serializer.save(updated_by=self.request.user)
        AuditLog.log(
            admin=self.request.user,
            action=AuditLog.Action.CONFIG_UPDATED,
            target=config,
            details={'key': config.key, 'new_value': config.value},
            request=self.request
        )


# === Audit Logs View ===

class AuditLogViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Consultation des logs d'audit (lecture seule).
    """
    permission_classes = [IsSuperAdmin]
    queryset = AuditLog.objects.select_related('admin').order_by('-created_at')
    serializer_class = AuditLogSerializer
    
    def get_queryset(self):
        queryset = super().get_queryset()
        
        # Filtres
        action = self.request.query_params.get('action')
        if action:
            queryset = queryset.filter(action=action)
        
        admin_id = self.request.query_params.get('admin')
        if admin_id:
            queryset = queryset.filter(admin_id=admin_id)
        
        # Date range
        date_from = self.request.query_params.get('from')
        if date_from:
            queryset = queryset.filter(created_at__date__gte=date_from)
        
        date_to = self.request.query_params.get('to')
        if date_to:
            queryset = queryset.filter(created_at__date__lte=date_to)
        
        return queryset[:500]  # Limite


# === Alert Rules Views ===

class AlertRuleViewSet(viewsets.ModelViewSet):
    """
    CRUD pour les regles d'alerte.
    """
    permission_classes = [IsSuperAdmin]
    queryset = AlertRule.objects.all()
    serializer_class = AlertRuleSerializer
