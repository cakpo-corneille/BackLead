import logging
from celery import shared_task
from django.utils import timezone
from datetime import timedelta
from decimal import Decimal

logger = logging.getLogger(__name__)


@shared_task(name='superadmin.calculate_daily_metrics')
def calculate_daily_metrics():
    """
    Calcule et enregistre les metriques journalieres.
    Execute chaque jour a minuit via Celery Beat.
    """
    from .models import DailyMetrics
    from accounts.models import Owner
    from subscriptions.models import Subscription, Payment
    from core_data.models import Lead, Widget
    from tracking.models import WiFiSession
    
    yesterday = (timezone.now() - timedelta(days=1)).date()
    
    # Creer ou recuperer les metriques du jour
    metrics, created = DailyMetrics.objects.get_or_create(date=yesterday)
    
    # === Owners ===
    metrics.total_owners = Owner.objects.filter(created_at__date__lte=yesterday).count()
    metrics.new_owners = Owner.objects.filter(created_at__date=yesterday).count()
    # Active = qui s'est connecte ce jour
    metrics.active_owners = Owner.objects.filter(
        user__last_login__date=yesterday
    ).count()
    
    # === Subscriptions ===
    subs = Subscription.objects.filter(created_at__date__lte=yesterday)
    metrics.total_subscriptions = subs.count()
    metrics.trial_subscriptions = subs.filter(status='trial').count()
    metrics.active_subscriptions = subs.filter(status='active').count()
    
    # Churns du jour
    metrics.churned_subscriptions = Subscription.objects.filter(
        cancelled_at__date=yesterday
    ).count()
    
    # Par plan
    from django.db.models import Count
    by_plan = dict(
        subs.filter(status__in=['active', 'trial']).values(
            'plan__slug'
        ).annotate(count=Count('id')).values_list('plan__slug', 'count')
    )
    metrics.subscriptions_by_plan = by_plan
    
    # === Revenue ===
    # MRR du jour
    mrr = Decimal('0')
    for sub in subs.filter(status='active').select_related('plan'):
        if sub.billing_cycle == 'yearly':
            mrr += sub.plan.price_yearly / 12
        else:
            mrr += sub.plan.price_monthly
    
    metrics.mrr = mrr
    metrics.arr = mrr * 12
    
    # Revenue du jour (paiements completes)
    revenue = Payment.objects.filter(
        status='completed',
        completed_at__date=yesterday
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0')
    metrics.revenue_today = revenue
    
    # === Usage ===
    metrics.total_leads = Lead.objects.filter(created_at__date__lte=yesterday).count()
    metrics.new_leads = Lead.objects.filter(created_at__date=yesterday).count()
    metrics.total_widgets = Widget.objects.filter(created_at__date__lte=yesterday).count()
    metrics.active_widgets = Widget.objects.filter(is_active=True).count()
    metrics.total_sessions = WiFiSession.objects.filter(started_at__date__lte=yesterday).count()
    metrics.new_sessions = WiFiSession.objects.filter(started_at__date=yesterday).count()
    
    metrics.save()
    
    logger.info(f"[Task] Daily metrics calculated for {yesterday}")
    return {
        'date': str(yesterday),
        'total_owners': metrics.total_owners,
        'mrr': float(metrics.mrr),
    }


@shared_task(name='superadmin.cache_realtime_kpis')
def cache_realtime_kpis():
    """
    Met en cache les KPIs temps reel.
    Execute toutes les 30 secondes via Celery Beat.
    """
    from .services import KPIService
    
    # Force le recalcul et la mise en cache
    kpis = KPIService.get_realtime_kpis(use_cache=False)
    
    logger.debug("[Task] Realtime KPIs cached")
    return {'timestamp': kpis['timestamp']}


@shared_task(name='superadmin.check_alert_rules')
def check_alert_rules():
    """
    Verifie les regles d'alerte et notifie si necessaire.
    Execute toutes les 5 minutes.
    """
    from .models import AlertRule
    from .services import KPIService
    import requests
    
    active_rules = AlertRule.objects.filter(is_active=True)
    kpis = KPIService.get_realtime_kpis(use_cache=False)
    
    triggered = []
    
    for rule in active_rules:
        # Recuperer la valeur de la metrique
        value = None
        
        if rule.metric == 'churn_rate':
            value = KPIService.calculate_churn_rate(30)
        elif rule.metric == 'error_rate':
            tech = kpis.get('technical', {})
            api_calls = tech.get('api_calls', 0)
            api_errors = tech.get('api_errors', 0)
            value = (api_errors / api_calls * 100) if api_calls > 0 else 0
        elif rule.metric == 'new_signups':
            value = kpis.get('owners', {}).get('new_today', 0)
        elif rule.metric == 'active_sessions':
            value = kpis.get('usage', {}).get('sessions', {}).get('active', 0)
        elif rule.metric == 'celery_failures':
            value = kpis.get('technical', {}).get('celery_tasks_failed', 0)
        
        if value is None:
            continue
        
        # Verifier la condition
        if rule.check_condition(value):
            triggered.append({
                'rule': rule.name,
                'metric': rule.metric,
                'value': value,
                'threshold': float(rule.threshold),
            })
            
            # Envoyer notification
            if rule.notify_email:
                # TODO: Envoyer email
                pass
            
            if rule.notify_webhook:
                try:
                    requests.post(rule.notify_webhook, json={
                        'alert': rule.name,
                        'metric': rule.metric,
                        'value': value,
                        'threshold': float(rule.threshold),
                        'timestamp': timezone.now().isoformat(),
                    }, timeout=10)
                except Exception as e:
                    logger.error(f"[Task] Failed to send webhook alert: {e}")
            
            # Mettre a jour last_triggered
            rule.last_triggered = timezone.now()
            rule.save(update_fields=['last_triggered'])
    
    if triggered:
        logger.warning(f"[Task] Alerts triggered: {triggered}")
    
    return {'triggered': len(triggered), 'alerts': triggered}


@shared_task(name='superadmin.cleanup_old_audit_logs')
def cleanup_old_audit_logs():
    """
    Nettoie les logs d'audit de plus d'un an.
    Execute mensuellement.
    """
    from .models import AuditLog
    
    cutoff = timezone.now() - timedelta(days=365)
    deleted, _ = AuditLog.objects.filter(created_at__lt=cutoff).delete()
    
    if deleted > 0:
        logger.info(f"[Task] Deleted {deleted} old audit logs")
    
    return {'deleted': deleted}


@shared_task(name='superadmin.generate_weekly_report')
def generate_weekly_report():
    """
    Genere un rapport hebdomadaire pour le superadmin.
    Execute chaque lundi a 8h.
    """
    from .models import DailyMetrics
    from .services import KPIService
    
    # Metriques de la semaine passee
    week_ago = timezone.now().date() - timedelta(days=7)
    
    weekly_metrics = DailyMetrics.objects.filter(date__gte=week_ago).order_by('date')
    
    if not weekly_metrics.exists():
        return {'status': 'no_data'}
    
    # Aggregations
    total_new_owners = sum(m.new_owners for m in weekly_metrics)
    total_new_leads = sum(m.new_leads for m in weekly_metrics)
    total_revenue = sum(m.revenue_today for m in weekly_metrics)
    avg_mrr = sum(m.mrr for m in weekly_metrics) / len(weekly_metrics)
    
    report = {
        'period': f'{week_ago} - {timezone.now().date()}',
        'new_owners': total_new_owners,
        'new_leads': total_new_leads,
        'total_revenue': float(total_revenue),
        'avg_mrr': float(avg_mrr),
        'current_kpis': KPIService.get_realtime_kpis(use_cache=False),
    }
    
    # TODO: Envoyer le rapport par email au superadmin
    logger.info(f"[Task] Weekly report generated: {report}")
    
    return report


# Import Sum pour calculate_daily_metrics
from django.db.models import Sum
