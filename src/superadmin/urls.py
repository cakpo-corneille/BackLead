from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    RealtimeKPIsView, RevenueKPIsView, HistoricalKPIsView, SystemHealthView,
    OwnerManagementViewSet, SubscriptionManagementViewSet,
    FeatureFlagViewSet, SystemConfigViewSet, AuditLogViewSet, AlertRuleViewSet
)

router = DefaultRouter()
router.register(r'owners', OwnerManagementViewSet, basename='superadmin-owner')
router.register(r'subscriptions', SubscriptionManagementViewSet, basename='superadmin-subscription')
router.register(r'flags', FeatureFlagViewSet, basename='feature-flag')
router.register(r'config', SystemConfigViewSet, basename='system-config')
router.register(r'audit-logs', AuditLogViewSet, basename='audit-log')
router.register(r'alerts', AlertRuleViewSet, basename='alert-rule')

urlpatterns = [
    # KPIs
    path('kpis/realtime/', RealtimeKPIsView.as_view(), name='kpis-realtime'),
    path('kpis/revenue/', RevenueKPIsView.as_view(), name='kpis-revenue'),
    path('kpis/history/', HistoricalKPIsView.as_view(), name='kpis-history'),
    
    # System Health
    path('health/', SystemHealthView.as_view(), name='system-health'),
    
    # Router URLs
    path('', include(router.urls)),
]
