from django.urls import path
from rest_framework import routers

from accounts.views import AuthViewSet, ProfileViewSet
from core_data.views import (
    AnalyticsViewSet,
    FormSchemaViewSet,
    PortalViewSet,
    LeadViewSet,
    ConflictAlertViewSet,
)
from tracking.views import (
    TicketPlanViewSet,
    ConnectionSessionViewSet,
    SessionAnalyticsViewSet,
    HotspotLoginView,
    HotspotLogoutView,
)
from assistant.views import AssistantViewSet, ChatConversationViewSet


class OptionalSlashRouter(routers.DefaultRouter):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.trailing_slash = '/?'


router = OptionalSlashRouter()

# Accounts
router.register(r'accounts/auth',     AuthViewSet,          basename='auth')
router.register(r'accounts/profile',  ProfileViewSet,       basename='profile')

# Core Data
router.register(r'leads',     LeadViewSet,          basename='leads')
router.register(r'alerts',    ConflictAlertViewSet,  basename='alerts')
router.register(r'analytics', AnalyticsViewSet,      basename='analytics')
router.register(r'schema',    FormSchemaViewSet,     basename='schema')
router.register(r'portal',    PortalViewSet,         basename='portal')

# Tracking
router.register(r'ticket-plans', TicketPlanViewSet, basename='ticket-plan')
router.register(r'sessions', ConnectionSessionViewSet, basename='session')
router.register(r'tracking-analytics', SessionAnalyticsViewSet, basename='tracking-analytics')

# Assistant IA
router.register(r'assistant', AssistantViewSet, basename='assistant')
router.register(r'assistant/conversations', ChatConversationViewSet, basename='conversations')

urlpatterns = [
    path('sessions/login/',  HotspotLoginView.as_view(),  name='hotspot-login'),
    path('sessions/logout/', HotspotLogoutView.as_view(), name='hotspot-logout'),
] + router.urls
