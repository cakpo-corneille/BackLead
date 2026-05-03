import logging
from celery import shared_task
from django.utils import timezone
from datetime import timedelta

logger = logging.getLogger(__name__)


@shared_task(name='subscriptions.check_pending_payments')
def check_pending_payments():
    """
    Verifie les paiements en attente aupres des operateurs Mobile Money.
    Execute toutes les 2 minutes via Celery Beat.
    """
    from .models import Payment
    from .services import PaymentService
    
    # Recuperer les paiements en attente depuis moins de 30 minutes
    cutoff = timezone.now() - timedelta(minutes=30)
    pending_payments = Payment.objects.filter(
        status__in=['pending', 'processing'],
        created_at__gte=cutoff
    )
    
    checked_count = 0
    completed_count = 0
    
    for payment in pending_payments:
        try:
            updated_payment = PaymentService.check_payment_status(payment)
            checked_count += 1
            
            if updated_payment.status == 'completed':
                completed_count += 1
                
        except Exception as e:
            logger.error(f"[Task] Error checking payment {payment.id}: {e}")
    
    logger.info(f"[Task] check_pending_payments: checked {checked_count}, completed {completed_count}")
    return {'checked': checked_count, 'completed': completed_count}


@shared_task(name='subscriptions.process_subscription_renewals')
def process_subscription_renewals():
    """
    Traite les renouvellements d'abonnements.
    Execute quotidiennement a 6h via Celery Beat.
    """
    from .models import Subscription
    
    # Abonnements actifs qui expirent dans les prochaines 24h
    tomorrow = timezone.now() + timedelta(days=1)
    expiring_soon = Subscription.objects.filter(
        status=Subscription.Status.ACTIVE,
        current_period_end__lte=tomorrow,
        current_period_end__gt=timezone.now()
    )
    
    renewed_count = 0
    
    for subscription in expiring_soon:
        # Verifier s'il y a un paiement recent complete
        recent_payment = subscription.payments.filter(
            status='completed',
            completed_at__gte=subscription.current_period_start
        ).exists()
        
        if recent_payment:
            subscription.renew()
            renewed_count += 1
            logger.info(f"[Task] Auto-renewed subscription {subscription.id}")
    
    logger.info(f"[Task] process_subscription_renewals: renewed {renewed_count}")
    return {'renewed': renewed_count}


@shared_task(name='subscriptions.expire_trial_subscriptions')
def expire_trial_subscriptions():
    """
    Expire les periodes d'essai terminees.
    Execute quotidiennement.
    """
    from .services import SubscriptionService
    
    count = SubscriptionService.check_and_expire_trials()
    logger.info(f"[Task] expire_trial_subscriptions: expired {count}")
    return {'expired': count}


@shared_task(name='subscriptions.suspend_overdue_subscriptions')
def suspend_overdue_subscriptions():
    """
    Suspend les abonnements non payes apres la periode de grace.
    Execute quotidiennement.
    """
    from .services import SubscriptionService
    
    count = SubscriptionService.check_and_suspend_overdue()
    logger.info(f"[Task] suspend_overdue_subscriptions: suspended {count}")
    return {'suspended': count}


@shared_task(name='subscriptions.send_payment_reminders')
def send_payment_reminders():
    """
    Envoie des rappels de paiement avant expiration.
    Execute quotidiennement a 9h.
    """
    from .models import Subscription
    # from core_data.services import NotificationService  # A implementer
    
    # Abonnements qui expirent dans 3 jours
    in_3_days = timezone.now() + timedelta(days=3)
    in_2_days = timezone.now() + timedelta(days=2)
    
    expiring_subscriptions = Subscription.objects.filter(
        status__in=[Subscription.Status.TRIAL, Subscription.Status.ACTIVE],
        current_period_end__gte=in_2_days,
        current_period_end__lte=in_3_days
    )
    
    sent_count = 0
    
    for subscription in expiring_subscriptions:
        try:
            # TODO: Envoyer notification email/SMS
            # NotificationService.send_renewal_reminder(subscription)
            sent_count += 1
            logger.info(f"[Task] Sent reminder to subscription {subscription.id}")
        except Exception as e:
            logger.error(f"[Task] Error sending reminder for {subscription.id}: {e}")
    
    logger.info(f"[Task] send_payment_reminders: sent {sent_count}")
    return {'sent': sent_count}


@shared_task(name='subscriptions.expire_old_pending_payments')
def expire_old_pending_payments():
    """
    Annule les paiements en attente depuis trop longtemps (> 1 heure).
    Execute toutes les 15 minutes.
    """
    from .models import Payment
    
    cutoff = timezone.now() - timedelta(hours=1)
    old_pending = Payment.objects.filter(
        status__in=['pending', 'processing'],
        created_at__lt=cutoff
    )
    
    expired_count = old_pending.update(
        status='cancelled',
        error_message='Paiement expire - delai depasse'
    )
    
    if expired_count > 0:
        logger.info(f"[Task] expire_old_pending_payments: expired {expired_count}")
    
    return {'expired': expired_count}


@shared_task(name='subscriptions.generate_monthly_invoices')
def generate_monthly_invoices():
    """
    Genere les factures pour le mois ecoule.
    Execute le 1er de chaque mois.
    """
    from .models import Subscription, Invoice
    from django.db.models import Q
    
    # Premier et dernier jour du mois precedent
    today = timezone.now().replace(day=1)
    last_month_end = today - timedelta(days=1)
    last_month_start = last_month_end.replace(day=1)
    
    # Abonnements actifs le mois dernier sans facture
    subscriptions_to_invoice = Subscription.objects.filter(
        status__in=[Subscription.Status.ACTIVE, Subscription.Status.CANCELLED],
        current_period_start__lte=last_month_end
    ).exclude(
        invoices__period_start__gte=last_month_start,
        invoices__period_end__lte=last_month_end
    )
    
    created_count = 0
    
    for subscription in subscriptions_to_invoice:
        try:
            invoice = Invoice.objects.create(
                subscription=subscription,
                amount=subscription.get_current_price(),
                currency=subscription.plan.currency,
                period_start=last_month_start,
                period_end=last_month_end,
                is_paid=True,  # Assume paye si abonnement actif
                billing_info={
                    'owner_name': subscription.owner.business_name,
                    'plan_name': subscription.plan.name,
                }
            )
            created_count += 1
            logger.info(f"[Task] Created invoice {invoice.invoice_number}")
        except Exception as e:
            logger.error(f"[Task] Error creating invoice for {subscription.id}: {e}")
    
    logger.info(f"[Task] generate_monthly_invoices: created {created_count}")
    return {'created': created_count}
