from typing import Any, Dict, List
from django.db.models import Max, Count
from django.db.models.functions import TruncHour
from django.core.cache import cache
from core_data.models import OwnerClient


def invalidate_analytics_cache(owner_id: int):
    """Supprime le cache des statistiques pour un owner spécifique."""
    cache_key = f'analytics_summary_{owner_id}'
    cache.delete(cache_key)


def analytics_history(owner_id: int) -> List[Dict[str, Any]]:
    """
    Retourne l'historique des statistiques mois par mois sur les 12 derniers mois.
    """
    cache_key = f'analytics_history_{owner_id}'
    cached_data = cache.get(cache_key)
    if cached_data:
        return cached_data

    from django.utils import timezone
    from datetime import timedelta, date as date_cls
    from django.db.models import Count, Sum
    from django.db.models.functions import TruncMonth
    from tracking.models import ConnectionSession  # type: ignore

    _FR_MONTHS = {
        1: 'Janvier', 2: 'Février', 3: 'Mars', 4: 'Avril',
        5: 'Mai', 6: 'Juin', 7: 'Juillet', 8: 'Août',
        9: 'Septembre', 10: 'Octobre', 11: 'Novembre', 12: 'Décembre',
    }

    now = timezone.now()

    # Générer les 12 premiers jours de mois exacts (mois courant inclus)
    months = []
    year, month = now.year, now.month
    for _ in range(12):
        months.append(date_cls(year, month, 1))
        month -= 1
        if month == 0:
            month = 12
            year -= 1
    # Du plus ancien au plus récent
    months.reverse()

    oldest = months[0]
    twelve_months_ago = timezone.datetime(oldest.year, oldest.month, 1,
                                          tzinfo=timezone.get_current_timezone())

    leads_history = (
        OwnerClient.objects.filter(owner_id=owner_id, created_at__gte=twelve_months_ago)
        .annotate(month=TruncMonth('created_at'))
        .values('month')
        .annotate(count=Count('id'))
    )
    leads_map = {entry['month'].date(): entry['count'] for entry in leads_history if entry['month']}

    sessions_history = (
        ConnectionSession.objects.filter(owner_id=owner_id, started_at__gte=twelve_months_ago)
        .annotate(month=TruncMonth('started_at'))
        .values('month')
        .annotate(count=Count('id'), revenue=Sum('ticket_plan__price_fcfa'))
    )
    sessions_map = {
        entry['month'].date(): {'count': entry['count'], 'revenue': entry['revenue'] or 0}
        for entry in sessions_history if entry['month']
    }

    results = []
    for first_day in reversed(months):
        sess_data = sessions_map.get(first_day, {'count': 0, 'revenue': 0})
        results.append({
            'month': first_day.isoformat(),
            'month_label': f"{_FR_MONTHS[first_day.month]} {first_day.year}",
            'leads': leads_map.get(first_day, 0),
            'sessions': sess_data['count'],
            'revenue': sess_data['revenue'],
        })

    cache.set(cache_key, results, timeout=3600)
    return results


def analytics_summary(owner_id: int, days: int = 7, date_from: str = None) -> Dict[str, Any]:
    """
    Retourne les statistiques pour un owner sur une période donnée avec mise en cache.
    date_from : date ISO (YYYY-MM-DD) — début calendaire de la période (jour/semaine/mois).
    """
    cache_key = f'analytics_summary_{owner_id}_{date_from or f"{days}d"}'
    cached_data = cache.get(cache_key)
    
    if cached_data:
        return cached_data

    from django.utils import timezone
    from datetime import timedelta, date as date_cls
    
    queryset = OwnerClient.objects.filter(owner_id=owner_id)
    total_leads = queryset.count()

    if date_from:
        try:
            from_date = date_cls.fromisoformat(date_from)
        except (ValueError, TypeError):
            from_date = timezone.now().date()
        period_queryset = queryset.filter(created_at__date__gte=from_date)
        # Clients de retour = vus dans la période MAIS inscrits avant la période
        returning_clients = queryset.filter(
            last_seen__date__gte=from_date,
            created_at__date__lt=from_date,
        ).count()
        total_seen_in_period = queryset.filter(last_seen__date__gte=from_date).count()
    else:
        period_ago = timezone.now() - timedelta(days=days)
        period_queryset = queryset.filter(created_at__gte=period_ago)
        # Clients de retour = vus dans la période MAIS inscrits avant la période
        returning_clients = queryset.filter(
            last_seen__gte=period_ago,
            created_at__lt=period_ago,
        ).count()
        total_seen_in_period = queryset.filter(last_seen__gte=period_ago).count()

    period_leads = period_queryset.count()
    period_verified = period_queryset.filter(is_verified=True).count()
    period_return_rate = round((returning_clients / total_seen_in_period * 100), 1) if total_seen_in_period > 0 else 0.0

    top_clients = _get_top_loyal_clients(queryset)
    leads_series = _get_leads_series(queryset, days, date_from=date_from)
    
    summary_data = {
        'total_leads': total_leads,
        'period_leads': period_leads,
        'period_verified_leads': period_verified,
        'period_return_rate': period_return_rate, 
        'top_clients': top_clients,
        'leads_series': leads_series,
        'period_days': days
    }

    cache.set(cache_key, summary_data, timeout=600)
    return summary_data


def _get_top_loyal_clients(queryset) -> List[Dict[str, Any]]:
    """
    Retourne les top 20 clients les plus fidèles.
    
    Critère : recognition_level >= max_recognition_level / 1.5
    
    Args:
        queryset: QuerySet filtré par owner
    
    Returns:
        Liste de max 20 clients triés par recognition_level décroissant
    """
    # Récupérer le max recognition_level de cet owner
    max_recognition = queryset.aggregate(Max('recognition_level'))['recognition_level__max']
    
    if not max_recognition or max_recognition == 0:
        return []
    
    # Seuil de fidélité
    threshold = max_recognition / 1.5
    
    # Récupérer les clients au-dessus du seuil
    loyal_clients = queryset.filter(
        recognition_level__gte=threshold
    ).order_by('-recognition_level', '-last_seen')[:20]
    
    # Formater les résultats
    results = []
    for client in loyal_clients:
        # Extraire le nom du payload
        name = None
        if client.payload:
            name = (
                client.payload.get('nom') or 
                client.payload.get('name') or 
                client.payload.get('prenom') or
                client.payload.get('firstname')
            )
        
        # Calculer le pourcentage de fidélité
        loyalty_percentage = round((client.recognition_level / max_recognition) * 100, 1)
        
        results.append({
            'id': client.id,
            'name': name,
            'first_name': client.first_name or None,
            'last_name': client.last_name or None,
            'email': client.email or None,
            'phone': client.phone or None,
            'mac_address': client.mac_address,
            'recognition_level': client.recognition_level,
            'loyalty_percentage': loyalty_percentage,
            'last_seen': client.last_seen.isoformat() if client.last_seen else None,
            'created_at': client.created_at.isoformat() if client.created_at else None,
            'is_verified': client.is_verified
        })
    
    return results


def _get_leads_series(queryset, days: int, date_from: str = None) -> List[Dict[str, Any]]:
    """
    Retourne la série temporelle des leads.
    - Si date_from == aujourd'hui (ou days==1) : par heure depuis minuit
    - Sinon : par jour depuis date_from
    """
    from django.utils import timezone
    from datetime import timedelta, date as date_cls
    from django.db.models.functions import TruncHour, TruncDay

    now = timezone.now()
    today = now.date()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    if date_from:
        try:
            from_date = date_cls.fromisoformat(date_from)
        except (ValueError, TypeError):
            from_date = today
        is_today_only = (from_date == today)
    else:
        from_date = (now - timedelta(days=days - 1)).date()
        is_today_only = (days == 1)

    if is_today_only:
        hourly_data = (
            queryset
            .filter(created_at__gte=today_start)
            .annotate(period=TruncHour('created_at'))
            .values('period')
            .annotate(count=Count('id'))
        )
        data_map = {entry['period']: entry['count'] for entry in hourly_data if entry['period']}
        results = []
        for i in range(24):
            target = today_start + timedelta(hours=i)
            results.append({'label': target.isoformat(), 'count': data_map.get(target, 0)})
        return results
    else:
        daily_data = (
            queryset
            .filter(created_at__date__gte=from_date)
            .annotate(period=TruncDay('created_at'))
            .values('period')
            .annotate(count=Count('id'))
        )
        data_map = {
            entry['period'].date() if hasattr(entry['period'], 'date') else entry['period']: entry['count']
            for entry in daily_data if entry['period']
        }
        results = []
        current = from_date
        while current <= today:
            results.append({'label': current.isoformat(), 'count': data_map.get(current, 0)})
            current = current + timedelta(days=1)
        return results