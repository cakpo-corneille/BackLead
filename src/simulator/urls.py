from django.urls import path

from .views import captive_portal_simulator

urlpatterns = [
    
    path('',captive_portal_simulator, name='portal'),
]


