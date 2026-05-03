import logging
from abc import ABC, abstractmethod
from decimal import Decimal
from typing import Optional
from django.conf import settings
from django.utils import timezone

from .models import Payment, Subscription, Invoice

logger = logging.getLogger(__name__)


class MobileMoneyError(Exception):
    """Exception pour les erreurs Mobile Money"""
    def __init__(self, message: str, code: str = None, details: dict = None):
        self.message = message
        self.code = code
        self.details = details or {}
        super().__init__(self.message)


class BaseMobileMoneyService(ABC):
    """
    Service abstrait pour les paiements Mobile Money.
    Implementez ce service pour chaque operateur.
    """
    
    @abstractmethod
    def initiate_payment(
        self,
        phone_number: str,
        amount: Decimal,
        reference: str,
        description: str = ''
    ) -> dict:
        """
        Initie une demande de paiement vers le mobile de l'utilisateur.
        
        Args:
            phone_number: Numero de telephone (format international)
            amount: Montant en XOF
            reference: Reference unique de la transaction
            description: Description du paiement
            
        Returns:
            dict avec:
                - transaction_id: ID de la transaction chez l'operateur
                - status: 'pending', 'processing', 'completed', 'failed'
                - message: Message de statut
        """
        pass
    
    @abstractmethod
    def check_status(self, transaction_id: str) -> dict:
        """
        Verifie le statut d'une transaction.
        
        Args:
            transaction_id: ID de la transaction retourne par initiate_payment
            
        Returns:
            dict avec:
                - status: 'pending', 'processing', 'completed', 'failed'
                - message: Message de statut
                - completed_at: Datetime si complete
        """
        pass
    
    @abstractmethod
    def refund(self, transaction_id: str, amount: Decimal = None) -> dict:
        """
        Rembourse une transaction.
        
        Args:
            transaction_id: ID de la transaction a rembourser
            amount: Montant a rembourser (None = remboursement total)
            
        Returns:
            dict avec statut du remboursement
        """
        pass


class MTNMoMoService(BaseMobileMoneyService):
    """
    Integration MTN Mobile Money Benin
    Documentation: https://momodeveloper.mtn.com/
    """
    
    def __init__(self):
        self.api_key = getattr(settings, 'MTN_MOMO_API_KEY', '')
        self.api_secret = getattr(settings, 'MTN_MOMO_API_SECRET', '')
        self.environment = getattr(settings, 'MTN_MOMO_ENVIRONMENT', 'sandbox')
        self.subscription_key = getattr(settings, 'MTN_MOMO_SUBSCRIPTION_KEY', '')
        
        # URLs selon l'environnement
        if self.environment == 'production':
            self.base_url = 'https://proxy.momoapi.mtn.com'
        else:
            self.base_url = 'https://sandbox.momodeveloper.mtn.com'
    
    def _get_access_token(self) -> str:
        """Obtient un token d'acces OAuth"""
        # TODO: Implementer l'authentification MTN MoMo
        # POST /collection/token/
        # Authorization: Basic base64(api_key:api_secret)
        logger.info("[MTN MoMo] Getting access token...")
        return "mock_access_token"
    
    def initiate_payment(
        self,
        phone_number: str,
        amount: Decimal,
        reference: str,
        description: str = ''
    ) -> dict:
        """
        Initie un paiement MTN MoMo (Request to Pay)
        
        Endpoint: POST /collection/v1_0/requesttopay
        """
        logger.info(f"[MTN MoMo] Initiating payment: {amount} XOF to {phone_number}")
        
        # TODO: Implementer l'appel API reel
        # Headers:
        #   - Authorization: Bearer {access_token}
        #   - X-Reference-Id: {reference}
        #   - X-Target-Environment: sandbox/production
        #   - Ocp-Apim-Subscription-Key: {subscription_key}
        # Body:
        #   - amount: str(amount)
        #   - currency: "XOF"
        #   - externalId: reference
        #   - payer: {"partyIdType": "MSISDN", "partyId": phone_number}
        #   - payerMessage: description
        #   - payeeNote: description
        
        # Mock response pour developpement
        return {
            'transaction_id': reference,
            'status': 'pending',
            'message': 'Paiement initie. Veuillez confirmer sur votre telephone.',
            'provider': 'mtn_momo'
        }
    
    def check_status(self, transaction_id: str) -> dict:
        """
        Verifie le statut d'un paiement MTN MoMo
        
        Endpoint: GET /collection/v1_0/requesttopay/{referenceId}
        """
        logger.info(f"[MTN MoMo] Checking status for: {transaction_id}")
        
        # TODO: Implementer l'appel API reel
        # Les statuts possibles: PENDING, SUCCESSFUL, FAILED
        
        # Mock response
        return {
            'status': 'pending',
            'message': 'Transaction en cours de traitement',
            'completed_at': None
        }
    
    def refund(self, transaction_id: str, amount: Decimal = None) -> dict:
        """MTN MoMo ne supporte pas les remboursements automatiques"""
        logger.warning(f"[MTN MoMo] Refund requested for {transaction_id} - manual process required")
        return {
            'status': 'manual_required',
            'message': 'Le remboursement MTN MoMo necessite une intervention manuelle'
        }


class MoovMoneyService(BaseMobileMoneyService):
    """
    Integration Moov Money Benin
    """
    
    def __init__(self):
        self.api_key = getattr(settings, 'MOOV_MONEY_API_KEY', '')
        self.merchant_id = getattr(settings, 'MOOV_MONEY_MERCHANT_ID', '')
        self.environment = getattr(settings, 'MOOV_MONEY_ENVIRONMENT', 'sandbox')
        
        # URL API Moov Money
        if self.environment == 'production':
            self.base_url = 'https://api.moov-africa.bj'
        else:
            self.base_url = 'https://sandbox.moov-africa.bj'
    
    def initiate_payment(
        self,
        phone_number: str,
        amount: Decimal,
        reference: str,
        description: str = ''
    ) -> dict:
        """Initie un paiement Moov Money"""
        logger.info(f"[Moov Money] Initiating payment: {amount} XOF to {phone_number}")
        
        # TODO: Implementer l'appel API reel selon la documentation Moov
        
        # Mock response
        return {
            'transaction_id': reference,
            'status': 'pending',
            'message': 'Paiement initie. Veuillez confirmer sur votre telephone.',
            'provider': 'moov_money'
        }
    
    def check_status(self, transaction_id: str) -> dict:
        """Verifie le statut d'un paiement Moov Money"""
        logger.info(f"[Moov Money] Checking status for: {transaction_id}")
        
        # TODO: Implementer l'appel API reel
        
        # Mock response
        return {
            'status': 'pending',
            'message': 'Transaction en cours de traitement',
            'completed_at': None
        }
    
    def refund(self, transaction_id: str, amount: Decimal = None) -> dict:
        """Rembourse un paiement Moov Money"""
        logger.warning(f"[Moov Money] Refund requested for {transaction_id}")
        return {
            'status': 'manual_required',
            'message': 'Le remboursement necessite une intervention manuelle'
        }


def get_mobile_money_service(provider: str) -> BaseMobileMoneyService:
    """
    Factory pour obtenir le service Mobile Money appropriate
    """
    services = {
        'mtn_momo': MTNMoMoService,
        'moov_money': MoovMoneyService,
    }
    
    service_class = services.get(provider)
    if not service_class:
        raise ValueError(f"Provider inconnu: {provider}")
    
    return service_class()


class SubscriptionService:
    """
    Service de gestion des abonnements
    """
    
    @staticmethod
    def create_subscription(owner, plan, billing_cycle: str = 'monthly') -> Subscription:
        """
        Cree un nouvel abonnement pour un owner.
        Demarre en mode trial si le plan le permet.
        """
        subscription = Subscription.objects.create(
            owner=owner,
            plan=plan,
            billing_cycle=billing_cycle,
            status=Subscription.Status.TRIAL if plan.trial_days > 0 else Subscription.Status.ACTIVE
        )
        logger.info(f"[Subscription] Created subscription {subscription.id} for owner {owner.id}")
        return subscription
    
    @staticmethod
    def upgrade_plan(subscription: Subscription, new_plan, billing_cycle: str = None) -> Subscription:
        """
        Upgrade/downgrade vers un nouveau plan.
        Le changement prend effet immediatement.
        """
        old_plan = subscription.plan
        subscription.plan = new_plan
        
        if billing_cycle:
            subscription.billing_cycle = billing_cycle
        
        # Reset usage si upgrade
        if new_plan.max_leads_per_month > old_plan.max_leads_per_month:
            subscription.leads_used = 0
        
        subscription.save()
        logger.info(f"[Subscription] Upgraded {subscription.id} from {old_plan.slug} to {new_plan.slug}")
        return subscription
    
    @staticmethod
    def process_successful_payment(payment: Payment) -> Subscription:
        """
        Traite un paiement reussi et active/renouvelle l'abonnement.
        """
        subscription = payment.subscription
        
        # Activer si trial ou past_due
        if subscription.status in [Subscription.Status.TRIAL, Subscription.Status.PAST_DUE]:
            subscription.activate()
        
        # Renouveler si fin de periode proche
        if subscription.days_until_renewal() <= 1:
            subscription.renew()
        
        # Creer la facture
        invoice = Invoice.objects.create(
            subscription=subscription,
            payment=payment,
            amount=payment.amount,
            currency=payment.currency,
            period_start=subscription.current_period_start,
            period_end=subscription.current_period_end,
            is_paid=True,
            paid_at=timezone.now(),
            billing_info={
                'owner_name': subscription.owner.business_name,
                'owner_email': subscription.owner.user.email,
                'plan_name': subscription.plan.name,
            }
        )
        
        logger.info(f"[Subscription] Payment processed, invoice {invoice.invoice_number} created")
        return subscription
    
    @staticmethod
    def check_and_expire_trials():
        """
        Verifie et expire les periodes d'essai terminees.
        A executer periodiquement via Celery.
        """
        expired_trials = Subscription.objects.filter(
            status=Subscription.Status.TRIAL,
            trial_end__lt=timezone.now()
        )
        
        count = 0
        for subscription in expired_trials:
            subscription.status = Subscription.Status.EXPIRED
            subscription.save()
            count += 1
            logger.info(f"[Subscription] Trial expired for subscription {subscription.id}")
        
        return count
    
    @staticmethod
    def check_and_suspend_overdue():
        """
        Suspend les abonnements non payes apres la fin de periode.
        A executer periodiquement via Celery.
        """
        grace_days = 3  # Jours de grace apres expiration
        
        overdue = Subscription.objects.filter(
            status=Subscription.Status.ACTIVE,
            current_period_end__lt=timezone.now() - timezone.timedelta(days=grace_days)
        )
        
        count = 0
        for subscription in overdue:
            subscription.suspend()
            count += 1
            logger.info(f"[Subscription] Suspended overdue subscription {subscription.id}")
        
        return count


class PaymentService:
    """
    Service de gestion des paiements Mobile Money
    """
    
    @staticmethod
    def initiate_payment(
        subscription: Subscription,
        provider: str,
        phone_number: str,
        amount: Decimal = None,
        description: str = ''
    ) -> Payment:
        """
        Initie un paiement Mobile Money pour un abonnement.
        """
        if amount is None:
            amount = subscription.get_current_price()
        
        if not description:
            description = f"Abonnement WiFiLeads - {subscription.plan.name}"
        
        # Creer le paiement en base
        payment = Payment.objects.create(
            subscription=subscription,
            amount=amount,
            currency=subscription.plan.currency,
            provider=provider,
            phone_number=phone_number,
            description=description,
            status=Payment.Status.PENDING
        )
        
        # Appeler le service Mobile Money
        try:
            mm_service = get_mobile_money_service(provider)
            result = mm_service.initiate_payment(
                phone_number=phone_number,
                amount=amount,
                reference=str(payment.uuid),
                description=description
            )
            
            payment.external_id = result.get('transaction_id')
            payment.metadata = result
            payment.status = Payment.Status.PROCESSING
            payment.save()
            
            logger.info(f"[Payment] Initiated payment {payment.id} via {provider}")
            
        except Exception as e:
            payment.mark_failed(str(e))
            logger.error(f"[Payment] Failed to initiate payment {payment.id}: {e}")
            raise MobileMoneyError(str(e))
        
        return payment
    
    @staticmethod
    def check_payment_status(payment: Payment) -> Payment:
        """
        Verifie le statut d'un paiement en cours.
        """
        if payment.status not in [Payment.Status.PENDING, Payment.Status.PROCESSING]:
            return payment
        
        try:
            mm_service = get_mobile_money_service(payment.provider)
            result = mm_service.check_status(payment.external_id or str(payment.uuid))
            
            status = result.get('status', '').lower()
            
            if status in ['successful', 'completed']:
                payment.mark_completed(payment.external_id)
                # Traiter le paiement reussi
                SubscriptionService.process_successful_payment(payment)
                
            elif status == 'failed':
                payment.mark_failed(result.get('message', 'Paiement echoue'))
            
            payment.metadata.update(result)
            payment.save()
            
        except Exception as e:
            logger.error(f"[Payment] Error checking status for {payment.id}: {e}")
        
        return payment
    
    @staticmethod
    def process_webhook(provider: str, data: dict) -> Optional[Payment]:
        """
        Traite un webhook de callback Mobile Money.
        """
        # Trouver le paiement via la reference externe
        external_id = data.get('externalId') or data.get('transaction_id') or data.get('reference')
        
        if not external_id:
            logger.warning(f"[Payment] Webhook without reference: {data}")
            return None
        
        try:
            payment = Payment.objects.get(
                external_id=external_id,
                provider=provider,
                status__in=[Payment.Status.PENDING, Payment.Status.PROCESSING]
            )
        except Payment.DoesNotExist:
            # Essayer avec UUID
            try:
                payment = Payment.objects.get(
                    uuid=external_id,
                    provider=provider,
                    status__in=[Payment.Status.PENDING, Payment.Status.PROCESSING]
                )
            except (Payment.DoesNotExist, ValueError):
                logger.warning(f"[Payment] Webhook for unknown payment: {external_id}")
                return None
        
        # Mettre a jour selon le statut
        status = data.get('status', '').lower()
        
        if status in ['successful', 'completed', 'success']:
            payment.mark_completed(external_id)
            SubscriptionService.process_successful_payment(payment)
            logger.info(f"[Payment] Webhook: payment {payment.id} completed")
            
        elif status in ['failed', 'rejected', 'cancelled']:
            payment.mark_failed(data.get('reason', 'Paiement refuse'))
            logger.info(f"[Payment] Webhook: payment {payment.id} failed")
        
        payment.metadata['webhook'] = data
        payment.save()
        
        return payment
