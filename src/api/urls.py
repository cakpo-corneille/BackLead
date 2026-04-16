from django.urls import path, include
from rest_framework import permissions
from drf_yasg.views import get_schema_view
from drf_yasg import openapi

from .healthcheck import healthcheck, readiness, liveness

# Swagger config
schema_view = get_schema_view(
    openapi.Info(
        title="WiFi-zone Leads API",
        default_version='v1',
        description="API REST pour la gestion WiFi Marketing",
    ),
    public=True,
    permission_classes=(permissions.AllowAny,),
)


urlpatterns = [
    # API versionnée
    path('v1/', include('api.v1')),
    
    # Health & monitoring
    path('health/', healthcheck, name='health'),
    path('ready/', readiness, name='ready'),
    path('alive/', liveness, name='alive'),
    
    # Documentation
    path('docs/', schema_view.with_ui('swagger', cache_timeout=0), name='docs'),
]