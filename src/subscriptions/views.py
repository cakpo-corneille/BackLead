import logging
from rest_framework import viewsets, status, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView
from django.shortcuts import get_object_or_404

from .models import Plan, Subscription, Payment, Invoice
from .serializers import (
    PlanSerializer, SubscriptionSerializer, SubscriptionSummarySerializer,
    UpgradeSubscriptionSerializer, CancelSubscriptionSerializer,
    InitiatePaymentSerializer, PaymentSerializer, PaymentDetailSerializer,
    InvoiceSerializer, InvoiceDetailSerializer
)
from .services import PaymentService, SubscriptionService, MobileMoneyError

logger = logging.getLogger(__name__)


class PlanViewSet(viewsets.ReadOnlyModelViewSet):
    """
    API pour consulter les plans d'abonnement disponibles.
    
    GET /api/v1/plans/ - Liste des plans actifs
    GET /api/v1/plans/{id}/ - Detail d'un plan
    """
    queryset = Plan.objects.filter(is_active=True).order_by('display_order', 'price_monthly')
    serializer_class = PlanSerializer
    permission_classes = [permissions.AllowAny]
    
    def get_queryset(self):
        queryset = super().get_queryset()
        # Filtre optionnel par slug
        slug = self.request.query_params.get('slug')
        if slug:
            queryset = queryset.filter(slug=slug)
        return queryset


class SubscriptionViewSet(viewsets.GenericViewSet):
    """
    API pour gerer l'abonnement de l'owner connecte.
    
    GET /api/v1/subscription/ - Abonnement actuel
    GET /api/v1/subscription/summary/ - Resume pour le dashboard
    POST /api/v1/subscription/upgrade/ - Changer de plan
    POST /api/v1/subscription/cancel/ - Annuler l'abonnement
    """
    permission_classes = [permissions.IsAuthenticated]
    
    def get_subscription(self):
        """Recupere l'abonnement de l'owner connecte"""
        owner = getattr(self.request.user, 'owner_profile', None)
        if not owner:
            return None
        return getattr(owner, 'subscription', None)
    
    def list(self, request):
        """GET /api/v1/subscription/ - Abonnement actuel"""
        subscription = self.get_subscription()
        if not subscription:
            return Response(
                {'detail': 'Aucun abonnement trouve.'},
                status=status.HTTP_404_NOT_FOUND
            )
        serializer = SubscriptionSerializer(subscription)
        return Response(serializer.data)
    
    @action(detail=False, methods=['get'])
    def summary(self, request):
        """GET /api/v1/subscription/summary/ - Resume pour le dashboard"""
        subscription = self.get_subscription()
        if not subscription:
            return Response(
                {'detail': 'Aucun abonnement trouve.'},
                status=status.HTTP_404_NOT_FOUND
            )
        serializer = SubscriptionSummarySerializer(subscription)
        return Response(serializer.data)
    
    @action(detail=False, methods=['post'])
    def upgrade(self, request):
        """POST /api/v1/subscription/upgrade/ - Changer de plan"""
        subscription = self.get_subscription()
        if not subscription:
            return Response(
                {'detail': 'Aucun abonnement trouve.'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        serializer = UpgradeSubscriptionSerializer(
            data=request.data,
            context={'subscription': subscription}
        )
        serializer.is_valid(raise_exception=True)
        
        new_plan = serializer.validated_data['plan_id']
        billing_cycle = serializer.validated_data.get('billing_cycle')
        
        # Effectuer l'upgrade
        subscription = SubscriptionService.upgrade_plan(
            subscription, new_plan, billing_cycle
        )
        
        return Response({
            'detail': f'Votre abonnement a ete mis a jour vers {new_plan.name}.',
            'subscription': SubscriptionSerializer(subscription).data
        })
    
    @action(detail=False, methods=['post'])
    def cancel(self, request):
        """POST /api/v1/subscription/cancel/ - Annuler l'abonnement"""
        subscription = self.get_subscription()
        if not subscription:
            return Response(
                {'detail': 'Aucun abonnement trouve.'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        if subscription.status == Subscription.Status.CANCELLED:
            return Response(
                {'detail': 'Cet abonnement est deja annule.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        serializer = CancelSubscriptionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        reason = serializer.validated_data.get('reason', '')
        subscription.cancel(reason)
        
        return Response({
            'detail': 'Votre abonnement a ete annule. Il restera actif jusqu\'a la fin de la periode en cours.',
            'current_period_end': subscription.current_period_end
        })


class PaymentViewSet(viewsets.GenericViewSet):
    """
    API pour gerer les paiements Mobile Money.
    
    POST /api/v1/payments/initiate/ - Initier un paiement
    GET /api/v1/payments/history/ - Historique des paiements
    GET /api/v1/payments/{id}/ - Detail d'un paiement
    GET /api/v1/payments/{id}/status/ - Verifier le statut
    """
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        owner = getattr(self.request.user, 'owner_profile', None)
        if not owner:
            return Payment.objects.none()
        return Payment.objects.filter(subscription__owner=owner)
    
    @action(detail=False, methods=['post'])
    def initiate(self, request):
        """POST /api/v1/payments/initiate/ - Initier un paiement"""
        owner = getattr(request.user, 'owner_profile', None)
        if not owner:
            return Response(
                {'detail': 'Profil proprietaire non trouve.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        subscription = getattr(owner, 'subscription', None)
        if not subscription:
            return Response(
                {'detail': 'Aucun abonnement trouve.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        serializer = InitiatePaymentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        provider = serializer.validated_data['provider']
        phone_number = serializer.validated_data['phone_number']
        plan = serializer.validated_data.get('plan_id')
        billing_cycle = serializer.validated_data.get('billing_cycle', subscription.billing_cycle)
        
        # Calculer le montant
        if plan:
            amount = plan.get_price(billing_cycle)
        else:
            amount = subscription.get_current_price()
        
        try:
            payment = PaymentService.initiate_payment(
                subscription=subscription,
                provider=provider,
                phone_number=phone_number,
                amount=amount
            )
            
            return Response({
                'detail': 'Paiement initie. Veuillez confirmer sur votre telephone.',
                'payment': PaymentSerializer(payment).data
            }, status=status.HTTP_201_CREATED)
            
        except MobileMoneyError as e:
            return Response(
                {'detail': str(e), 'code': e.code},
                status=status.HTTP_400_BAD_REQUEST
            )
    
    @action(detail=False, methods=['get'])
    def history(self, request):
        """GET /api/v1/payments/history/ - Historique des paiements"""
        payments = self.get_queryset().order_by('-created_at')[:50]
        serializer = PaymentSerializer(payments, many=True)
        return Response(serializer.data)
    
    def retrieve(self, request, pk=None):
        """GET /api/v1/payments/{id}/ - Detail d'un paiement"""
        payment = get_object_or_404(self.get_queryset(), pk=pk)
        serializer = PaymentDetailSerializer(payment)
        return Response(serializer.data)
    
    @action(detail=True, methods=['get'])
    def check_status(self, request, pk=None):
        """GET /api/v1/payments/{id}/status/ - Verifier le statut"""
        payment = get_object_or_404(self.get_queryset(), pk=pk)
        
        # Verifier le statut via l'API Mobile Money
        payment = PaymentService.check_payment_status(payment)
        
        return Response({
            'status': payment.status,
            'status_display': payment.get_status_display(),
            'completed_at': payment.completed_at
        })


class PaymentCallbackView(APIView):
    """
    Webhook pour recevoir les callbacks Mobile Money.
    
    POST /api/v1/payments/callback/mtn/ - Callback MTN MoMo
    POST /api/v1/payments/callback/moov/ - Callback Moov Money
    """
    permission_classes = [permissions.AllowAny]
    
    def post(self, request, provider):
        """Traite le callback d'un operateur Mobile Money"""
        logger.info(f"[Webhook] Received callback from {provider}: {request.data}")
        
        if provider not in ['mtn', 'moov']:
            return Response(
                {'detail': 'Provider inconnu'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Mapper vers le provider interne
        provider_map = {
            'mtn': 'mtn_momo',
            'moov': 'moov_money'
        }
        
        payment = PaymentService.process_webhook(
            provider=provider_map[provider],
            data=request.data
        )
        
        if payment:
            return Response({'status': 'ok', 'payment_id': payment.id})
        
        return Response({'status': 'ignored'})


class InvoiceViewSet(viewsets.ReadOnlyModelViewSet):
    """
    API pour consulter les factures.
    
    GET /api/v1/invoices/ - Liste des factures
    GET /api/v1/invoices/{id}/ - Detail d'une facture
    """
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        owner = getattr(self.request.user, 'owner_profile', None)
        if not owner:
            return Invoice.objects.none()
        return Invoice.objects.filter(subscription__owner=owner)
    
    def get_serializer_class(self):
        if self.action == 'retrieve':
            return InvoiceDetailSerializer
        return InvoiceSerializer
    
    @action(detail=True, methods=['get'])
    def download(self, request, pk=None):
        """GET /api/v1/invoices/{id}/download/ - Telecharger le PDF"""
        invoice = get_object_or_404(self.get_queryset(), pk=pk)
        
        if not invoice.pdf_url:
            return Response(
                {'detail': 'PDF non disponible pour cette facture.'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        return Response({'pdf_url': invoice.pdf_url})
