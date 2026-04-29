from rest_framework import routers
from accounts.views import AuthViewSet, ProfileViewSet
from core_data.views import (
    AnalyticsViewSet, 
    FormSchemaViewSet, 
    PortalViewSet, 
    LeadViewSet,
    ConflictAlertViewSet
)
from tracking.views import (
    TrackingViewSet,
    TicketPlanViewSet,
    MikroTikRouterViewSet,
    SessionAnalyticsViewSet,
    ConnectionSessionViewSet,
)
from assistant.views import AssistantViewSet, ChatConversationViewSet


class OptionalSlashRouter(routers.DefaultRouter):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Le point d'interrogation rend le slash précédent optionnel
        self.trailing_slash = '/?'
        
router = OptionalSlashRouter()

# Accounts
router.register(r'accounts/auth', AuthViewSet, basename='auth')
router.register(r'accounts/profile', ProfileViewSet, basename='profile')


# Core Data
router.register(r'leads', LeadViewSet, basename='leads')
router.register(r'alerts', ConflictAlertViewSet, basename='alerts')
router.register(r'analytics', AnalyticsViewSet, basename='analytics')
router.register(r'schema', FormSchemaViewSet, basename='schema')

# Core Data - Public portal
router.register(r'portal', PortalViewSet, basename='portal')

# Tracking - Public (tracker.js : status.html / logout.html)
router.register(r'tracking', TrackingViewSet, basename='tracking')

# Tracking - Dashboard owner (authentifié)
router.register(r'ticket-plans', TicketPlanViewSet, basename='ticket-plans')
router.register(r'routers', MikroTikRouterViewSet, basename='routers')
router.register(r'sessions', ConnectionSessionViewSet, basename='sessions')
router.register(r'session-analytics', SessionAnalyticsViewSet, basename='session-analytics')

# Assistant IA (Gemini via Replit AI Integrations)
router.register(r'assistant', AssistantViewSet, basename='assistant')
router.register(r'assistant/conversations', ChatConversationViewSet, basename='conversations')


urlpatterns = router.urls

# Additional API endpoints can be registered here in the future
