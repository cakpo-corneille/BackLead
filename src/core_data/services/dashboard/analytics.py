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
    from datetime import timedelta
    from django.db.models import Count, Sum
    from django.db.models.functions import TruncMonth
    from core_data.models import OwnerClient
    # Correction : Le modèle s'appelle ConnectionSession
    from tracking.models import ConnectionSession # type: ignore
    
    now = timezone.now()
    twelve_months_ago = (now - timedelta(days=365)).replace(day=1, hour=0, minute=0, second=0)
    
    # 1. Leads par mois
    leads_history = (
        OwnerClient.objects.filter(owner_id=owner_id, created_at__gte=twelve_months_ago)
        .annotate(month=TruncMonth('created_at'))
        .values('month')
        .annotate(count=Count('id'))
        .order_by('-month')
    )
    leads_map = {entry['month'].date(): entry['count'] for entry in leads_history if entry['month']}
    
    # 2. Sessions et Revenus par mois
    # On filtre les sessions appartenant à cet owner via le champ owner direct
    sessions_history = (
        ConnectionSession.objects.filter(owner_id=owner_id, started_at__gte=twelve_months_ago)
        .annotate(month=TruncMonth('started_at'))
        .values('month')
        .annotate(
            count=Count('id'),
            revenue=Sum('ticket_plan__price_fcfa') 
        )
        .order_by('-month')
    )
    sessions_map = {
        entry['month'].date(): {
            'count': entry['count'],
            'revenue': entry['revenue'] or 0
        } 
        for entry in sessions_history if entry['month']
    }
    
    # Générer la liste des 12 derniers mois
    results = []
    for i in range(12):
        # On remonte de i mois
        first_day_of_month = (now.replace(day=1) - timedelta(days=i*31)).replace(day=1, hour=0, minute=0, second=0)
        month_date = first_day_of_month.date()
        
        leads_count = leads_map.get(month_date, 0)
        sess_data = sessions_map.get(month_date, {'count': 0, 'revenue': 0})
        
        results.append({
            'month': month_date.isoformat(),
            'month_label': first_day_of_month.strftime('%B %Y'),
            'leads': leads_count,
            'sessions': sess_data['count'],
            'revenue': sess_data['revenue']
        })
    
    cache.set(cache_key, results, timeout=3600)
    return results


def analytics_summary(owner_id: int, days: int = 7) -> Dict[str, Any]:
    """
    Retourne les statistiques pour un owner sur une période donnée avec mise en cache.
    """
    cache_key = f'analytics_summary_{owner_id}_{days}d'
    cached_data = cache.get(cache_key)
    
    if cached_data:
        return cached_data

    from django.utils import timezone
    from datetime import timedelta
    
    queryset = OwnerClient.objects.filter(owner_id=owner_id)
    
    # 1. Clients totaux (Toujours tout le temps)
    total_leads = queryset.count()
    
    # Seuil temporel pour la période
    period_ago = timezone.now() - timedelta(days=days)
    period_queryset = queryset.filter(created_at__gte=period_ago)
    
    # 2. Nouveaux clients sur la période
    period_leads = period_queryset.count()
    
    # 3. Clients vérifiés sur la période
    period_verified = period_queryset.filter(is_verified=True).count()

    # 4. Taux de retour (clients revenus sur la période)
    # On regarde les clients qui ont été vus sur la période (last_seen) 
    # et qui ont un recognition_level > 1 (ils sont déjà venus avant)
    returning_clients = queryset.filter(
        last_seen__gte=period_ago,
        recognition_level__gt=1
    ).count()
    
    # Le taux de retour est calculé par rapport au nombre total de sessions ou de clients vus
    # Ici on va rester simple : (clients déjà connus vus / total vus)
    total_seen_in_period = queryset.filter(last_seen__gte=period_ago).count()
    period_return_rate = round((returning_clients / total_seen_in_period * 100), 1) if total_seen_in_period > 0 else 0.0
    
    # Top clients fidèles (Basé sur le queryset global pour la fidélité historique)
    top_clients = _get_top_loyal_clients(queryset)
    
    # Distribution temporelle (par heure pour 1j, par jour sinon)
    leads_series = _get_leads_series(queryset, days)
    
    summary_data = {
        'total_leads': total_leads,
        'period_leads': period_leads,
        'period_verified_leads': period_verified,
        'period_return_rate': period_return_rate, 
        'top_clients': top_clients,
        'leads_series': leads_series,
        'period_days': days
    }

    # Mise en cache pour 10 min pour les stats dynamiques
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


def _get_leads_series(queryset, days: int) -> List[Dict[str, Any]]:
    """
    Retourne la série temporelle des leads.
    - Si days=1 : par heure (dernières 24h)
    - Si days>1 : par jour (derniers X jours)
    """
    from django.utils import timezone
    from datetime import timedelta
    from django.db.models.functions import TruncHour, TruncDay
    
    now = timezone.now()
    
    if days == 1:
        # Par heure (24h)
        start_date = now.replace(minute=0, second=0, microsecond=0) - timedelta(hours=23)
        hourly_data = (
            queryset
            .filter(created_at__gte=start_date)
            .annotate(period=TruncHour('created_at'))
            .values('period')
            .annotate(count=Count('id'))
        )
        data_map = {entry['period']: entry['count'] for entry in hourly_data if entry['period']}
        
        results = []
        for i in range(24):
            target = start_date + timedelta(hours=i)
            results.append({
                'label': target.isoformat(),
                'count': data_map.get(target, 0)
            })
        return results
    else:
        # Par jour (X jours)
        start_date = (now - timedelta(days=days-1)).date()
        daily_data = (
            queryset
            .filter(created_at__date__gte=start_date)
            .annotate(period=TruncDay('created_at'))
            .values('period')
            .annotate(count=Count('id'))
        )
        # Convertir les dates du QuerySet en format date pour le mapping
        data_map = {entry['period'].date() if hasattr(entry['period'], 'date') else entry['period']: entry['count'] for entry in daily_data if entry['period']}
        
        results = []
        for i in range(days):
            target = start_date + timedelta(days=i)
            results.append({
                'label': target.isoformat() if hasattr(target, 'isoformat') else str(target),
                'count': data_map.get(target, 0)
            })
        return results