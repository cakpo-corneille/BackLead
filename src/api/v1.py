from rest_framework import routers
from accounts.views import AuthViewSet, ProfileViewSet
from core_data.views import AnalyticsViewSet, FormSchemaViewSet, PortalViewSet, LeadViewSet


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
router.register(r'analytics', AnalyticsViewSet, basename='analytics')
router.register(r'schema', FormSchemaViewSet, basename='schema')

# Core Data - Public portal
router.register(r'portal', PortalViewSet, basename='portal')


urlpatterns = router.urls

# Additional API endpoints can be registered here in the future
