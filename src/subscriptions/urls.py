from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    PlanViewSet, SubscriptionViewSet, PaymentViewSet,
    PaymentCallbackView, InvoiceViewSet
)

router = DefaultRouter()
router.register(r'plans', PlanViewSet, basename='plan')
router.register(r'subscription', SubscriptionViewSet, basename='subscription')
router.register(r'payments', PaymentViewSet, basename='payment')
router.register(r'invoices', InvoiceViewSet, basename='invoice')

urlpatterns = [
    path('', include(router.urls)),
    path('payments/callback/<str:provider>/', PaymentCallbackView.as_view(), name='payment-callback'),
]
