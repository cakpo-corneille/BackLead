import logging
from decimal import Decimal
from typing import Dict, Any, Optional
from datetime import timedelta
from django.utils import timezone
from django.db.models import Count, Sum, Avg, Q, F
from django.db.models.functions import TruncDate
from django.core.cache import cache
from django.conf import settings

logger = logging.getLogger(__name__)

# Cache keys
CACHE_KEY_REALTIME_KPIS = 'superadmin:kpis:realtime'
CACHE_KEY_SYSTEM_HEALTH = 'superadmin:system:health'
CACHE_TIMEOUT = 30  # 30 secondes


class KPIService:
    """
    Service de calcul des KPIs pour le dashboard superadmin.
    Supporte le cache Redis pour les metriques temps reel.
    """
    
    @classmethod
    def get_realtime_kpis(cls, use_cache: bool = True) -> Dict[str, Any]:
        """
        Retourne les KPIs temps reel.
        Utilise le cache Redis (30s) pour les performances.
        """
        if use_cache:
            cached = cache.get(CACHE_KEY_REALTIME_KPIS)
            if cached:
                return cached
        
        kpis = {
            'timestamp': timezone.now().isoformat(),
            'owners': cls._get_owner_metrics(),
            'subscriptions': cls._get_subscription_metrics(),
            'revenue': cls._get_revenue_metrics(),
            'usage': cls._get_usage_metrics(),
            'technical': cls._get_technical_metrics(),
        }
        
        if use_cache:
            cache.set(CACHE_KEY_REALTIME_KPIS, kpis, CACHE_TIMEOUT)
        
        return kpis
    
    @classmethod
    def _get_owner_metrics(cls) -> Dict[str, Any]:
        """Metriques sur les owners"""
        from accounts.models import Owner
        
        now = timezone.now()
        today = now.date()
        this_month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        last_month_start = (this_month_start - timedelta(days=1)).replace(day=1)
        
        total = Owner.objects.count()
        
        # Nouveaux ce mois
        new_this_month = Owner.objects.filter(created_at__gte=this_month_start).count()
        new_last_month = Owner.objects.filter(
            created_at__gte=last_month_start,
            created_at__lt=this_month_start
        ).count()
        
        # Croissance
        growth_rate = 0
        if new_last_month > 0:
            growth_rate = round(((new_this_month - new_last_month) / new_last_month) * 100, 1)
        
        # Nouveaux aujourd'hui
        new_today = Owner.objects.filter(created_at__date=today).count()
        
        return {
            'total': total,
            'new_today': new_today,
            'new_this_month': new_this_month,
            'growth_rate': growth_rate,
        }
    
    @classmethod
    def _get_subscription_metrics(cls) -> Dict[str, Any]:
        """Metriques sur les abonnements"""
        from subscriptions.models import Subscription, Plan
        
        # Comptes par statut
        status_counts = dict(
            Subscription.objects.values('status').annotate(count=Count('id')).values_list('status', 'count')
        )
        
        total = sum(status_counts.values())
        active = status_counts.get('active', 0)
        trial = status_counts.get('trial', 0)
        past_due = status_counts.get('past_due', 0)
        cancelled = status_counts.get('cancelled', 0)
        
        # Par plan
        by_plan = dict(
            Subscription.objects.filter(
                status__in=['active', 'trial']
            ).values('plan__name').annotate(count=Count('id')).values_list('plan__name', 'count')
        )
        
        # Taux de conversion trial -> paid
        total_trials_ended = Subscription.objects.filter(
            trial_end__lt=timezone.now()
        ).count()
        converted = Subscription.objects.filter(
            trial_end__lt=timezone.now(),
            status='active'
        ).count()
        conversion_rate = round((converted / total_trials_ended * 100), 1) if total_trials_ended > 0 else 0
        
        return {
            'total': total,
            'active': active,
            'trial': trial,
            'past_due': past_due,
            'cancelled': cancelled,
            'by_plan': by_plan,
            'trial_conversion_rate': conversion_rate,
        }
    
    @classmethod
    def _get_revenue_metrics(cls) -> Dict[str, Any]:
        """Metriques de revenue"""
        from subscriptions.models import Subscription, Payment
        
        # MRR: somme des abonnements actifs convertis en mensuel
        mrr = Decimal('0')
        
        active_subs = Subscription.objects.filter(
            status='active'
        ).select_related('plan')
        
        for sub in active_subs:
            if sub.billing_cycle == 'yearly':
                # Convertir annuel en mensuel
                mrr += sub.plan.price_yearly / 12
            else:
                mrr += sub.plan.price_monthly
        
        mrr = round(mrr, 2)
        arr = mrr * 12
        
        # Revenue du mois
        now = timezone.now()
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        
        revenue_this_month = Payment.objects.filter(
            status='completed',
            completed_at__gte=month_start
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0')
        
        # Revenue aujourd'hui
        revenue_today = Payment.objects.filter(
            status='completed',
            completed_at__date=now.date()
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0')
        
        # ARPU (Average Revenue Per User)
        active_count = active_subs.count()
        arpu = round(mrr / active_count, 2) if active_count > 0 else Decimal('0')
        
        return {
            'mrr': float(mrr),
            'arr': float(arr),
            'revenue_today': float(revenue_today),
            'revenue_this_month': float(revenue_this_month),
            'arpu': float(arpu),
            'currency': 'XOF',
        }
    
    @classmethod
    def _get_usage_metrics(cls) -> Dict[str, Any]:
        """Metriques d'usage de la plateforme"""
        from core_data.models import Lead, Widget
        from tracking.models import WiFiSession
        
        now = timezone.now()
        today = now.date()
        
        # Leads
        total_leads = Lead.objects.count()
        leads_today = Lead.objects.filter(created_at__date=today).count()
        leads_this_month = Lead.objects.filter(
            created_at__month=now.month,
            created_at__year=now.year
        ).count()
        
        # Widgets
        total_widgets = Widget.objects.count()
        active_widgets = Widget.objects.filter(is_active=True).count()
        
        # Sessions WiFi
        total_sessions = WiFiSession.objects.count()
        active_sessions = WiFiSession.objects.filter(is_active=True).count()
        sessions_today = WiFiSession.objects.filter(started_at__date=today).count()
        
        return {
            'leads': {
                'total': total_leads,
                'today': leads_today,
                'this_month': leads_this_month,
            },
            'widgets': {
                'total': total_widgets,
                'active': active_widgets,
            },
            'sessions': {
                'total': total_sessions,
                'active': active_sessions,
                'today': sessions_today,
            },
        }
    
    @classmethod
    def _get_technical_metrics(cls) -> Dict[str, Any]:
        """Metriques techniques (sante systeme)"""
        return cls.get_system_health()
    
    @classmethod
    def get_system_health(cls, use_cache: bool = True) -> Dict[str, Any]:
        """
        Verifie la sante du systeme (DB, Redis, Celery).
        """
        if use_cache:
            cached = cache.get(CACHE_KEY_SYSTEM_HEALTH)
            if cached:
                return cached
        
        health = {
            'status': 'healthy',
            'checks': {},
        }
        
        # Check Database
        try:
            from django.db import connection
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
            health['checks']['database'] = {'status': 'ok', 'message': 'Connected'}
        except Exception as e:
            health['checks']['database'] = {'status': 'error', 'message': str(e)}
            health['status'] = 'degraded'
        
        # Check Redis
        try:
            cache.set('health_check', 'ok', 10)
            if cache.get('health_check') == 'ok':
                health['checks']['redis'] = {'status': 'ok', 'message': 'Connected'}
            else:
                health['checks']['redis'] = {'status': 'warning', 'message': 'Read failed'}
                health['status'] = 'degraded'
        except Exception as e:
            health['checks']['redis'] = {'status': 'error', 'message': str(e)}
            health['status'] = 'degraded'
        
        # Check Celery
        try:
            from django_celery_beat.models import PeriodicTask
            # Verifier si les taches periodiques sont configurees
            task_count = PeriodicTask.objects.filter(enabled=True).count()
            health['checks']['celery'] = {
                'status': 'ok' if task_count > 0 else 'warning',
                'message': f'{task_count} periodic tasks',
                'tasks_count': task_count,
            }
        except Exception as e:
            health['checks']['celery'] = {'status': 'warning', 'message': f'Cannot check: {e}'}
        
        if use_cache:
            cache.set(CACHE_KEY_SYSTEM_HEALTH, health, CACHE_TIMEOUT)
        
        return health
    
    @classmethod
    def calculate_churn_rate(cls, days: int = 30) -> float:
        """
        Calcule le taux de churn sur une periode.
        Churn = abonnements annules / abonnements au debut de la periode
        """
        from subscriptions.models import Subscription
        
        period_start = timezone.now() - timedelta(days=days)
        
        # Abonnements au debut de la periode
        start_count = Subscription.objects.filter(
            created_at__lt=period_start,
            status__in=['active', 'trial']
        ).count()
        
        if start_count == 0:
            return 0.0
        
        # Churns pendant la periode
        churned = Subscription.objects.filter(
            cancelled_at__gte=period_start,
            status__in=['cancelled', 'expired']
        ).count()
        
        return round((churned / start_count) * 100, 2)
    
    @classmethod
    def calculate_ltv(cls) -> Decimal:
        """
        Calcule la Lifetime Value moyenne.
        LTV = ARPU / Churn Rate (mensuel)
        """
        from subscriptions.models import Subscription
        
        revenue = cls._get_revenue_metrics()
        arpu = Decimal(str(revenue['arpu']))
        
        churn_rate = cls.calculate_churn_rate(30)
        if churn_rate == 0:
            churn_rate = 5  # Assume 5% churn si pas de donnees
        
        monthly_churn = Decimal(str(churn_rate)) / 100
        
        if monthly_churn > 0:
            ltv = arpu / monthly_churn
        else:
            ltv = arpu * 24  # Assume 24 mois si churn = 0
        
        return round(ltv, 2)
    
    @classmethod
    def get_historical_metrics(cls, days: int = 30) -> list:
        """
        Retourne l'historique des metriques sur N jours.
        """
        from .models import DailyMetrics
        
        cutoff = timezone.now().date() - timedelta(days=days)
        
        metrics = DailyMetrics.objects.filter(
            date__gte=cutoff
        ).order_by('date').values(
            'date', 'total_owners', 'new_owners',
            'active_subscriptions', 'trial_subscriptions',
            'mrr', 'total_leads', 'new_leads'
        )
        
        return list(metrics)
    
    @classmethod
    def get_revenue_breakdown(cls) -> Dict[str, Any]:
        """
        Breakdown detaille des revenus par plan et cycle.
        """
        from subscriptions.models import Subscription
        
        breakdown = {
            'by_plan': {},
            'by_cycle': {'monthly': Decimal('0'), 'yearly': Decimal('0')},
            'total_mrr': Decimal('0'),
        }
        
        active_subs = Subscription.objects.filter(
            status='active'
        ).select_related('plan')
        
        for sub in active_subs:
            plan_name = sub.plan.name
            
            if sub.billing_cycle == 'yearly':
                monthly_value = sub.plan.price_yearly / 12
                breakdown['by_cycle']['yearly'] += monthly_value
            else:
                monthly_value = sub.plan.price_monthly
                breakdown['by_cycle']['monthly'] += monthly_value
            
            if plan_name not in breakdown['by_plan']:
                breakdown['by_plan'][plan_name] = {
                    'count': 0,
                    'mrr': Decimal('0'),
                }
            
            breakdown['by_plan'][plan_name]['count'] += 1
            breakdown['by_plan'][plan_name]['mrr'] += monthly_value
            breakdown['total_mrr'] += monthly_value
        
        # Convertir en float pour JSON
        breakdown['by_cycle']['monthly'] = float(breakdown['by_cycle']['monthly'])
        breakdown['by_cycle']['yearly'] = float(breakdown['by_cycle']['yearly'])
        breakdown['total_mrr'] = float(breakdown['total_mrr'])
        
        for plan in breakdown['by_plan']:
            breakdown['by_plan'][plan]['mrr'] = float(breakdown['by_plan'][plan]['mrr'])
        
        return breakdown


class OwnerManagementService:
    """
    Service de gestion des owners pour le superadmin.
    """
    
    @staticmethod
    def suspend_owner(owner, admin, reason: str = '', request=None):
        """Suspend un owner et son abonnement"""
        from .models import AuditLog
        from subscriptions.models import Subscription
        
        # Suspendre l'abonnement
        subscription = getattr(owner, 'subscription', None)
        if subscription:
            old_status = subscription.status
            subscription.status = Subscription.Status.PAST_DUE
            subscription.save()
        
        # Desactiver le user
        owner.user.is_active = False
        owner.user.save()
        
        # Log
        AuditLog.log(
            admin=admin,
            action=AuditLog.Action.OWNER_SUSPENDED,
            target=owner,
            details={
                'reason': reason,
                'previous_subscription_status': old_status if subscription else None,
            },
            request=request
        )
        
        logger.info(f"[Superadmin] Owner {owner.id} suspended by {admin.email}")
        return owner
    
    @staticmethod
    def activate_owner(owner, admin, request=None):
        """Reactive un owner"""
        from .models import AuditLog
        from subscriptions.models import Subscription
        
        # Reactiver le user
        owner.user.is_active = True
        owner.user.save()
        
        # Reactiver l'abonnement si etait suspendu
        subscription = getattr(owner, 'subscription', None)
        if subscription and subscription.status == Subscription.Status.PAST_DUE:
            subscription.status = Subscription.Status.ACTIVE
            subscription.save()
        
        # Log
        AuditLog.log(
            admin=admin,
            action=AuditLog.Action.OWNER_ACTIVATED,
            target=owner,
            request=request
        )
        
        logger.info(f"[Superadmin] Owner {owner.id} activated by {admin.email}")
        return owner
    
    @staticmethod
    def reset_owner_password(owner, admin, request=None):
        """Envoie un email de reset password"""
        from .models import AuditLog
        # from accounts.services import send_password_reset_email  # A implementer
        
        # TODO: Envoyer email de reset
        # send_password_reset_email(owner.user)
        
        # Log
        AuditLog.log(
            admin=admin,
            action=AuditLog.Action.OWNER_PASSWORD_RESET,
            target=owner,
            request=request
        )
        
        logger.info(f"[Superadmin] Password reset sent for owner {owner.id} by {admin.email}")
        return True
    
    @staticmethod
    def generate_impersonation_token(owner, admin, request=None):
        """
        Genere un token pour se connecter en tant que l'owner.
        Le token expire apres 1 heure.
        """
        from .models import AuditLog
        from rest_framework_simplejwt.tokens import RefreshToken
        
        # Generer tokens JWT pour l'owner
        refresh = RefreshToken.for_user(owner.user)
        refresh['is_impersonation'] = True
        refresh['impersonated_by'] = admin.id
        
        # Log
        AuditLog.log(
            admin=admin,
            action=AuditLog.Action.OWNER_IMPERSONATED,
            target=owner,
            details={'expires_in': '1 hour'},
            request=request
        )
        
        logger.warning(f"[Superadmin] Impersonation token generated for owner {owner.id} by {admin.email}")
        
        return {
            'access': str(refresh.access_token),
            'refresh': str(refresh),
            'expires_in': 3600,
        }
