from typing import Any, Dict, List
from django.db.models import Max, Count
from django.db.models.functions import TruncHour
from core_data.models import OwnerClient


def analytics_summary(owner_id: int) -> Dict[str, Any]:
    """
    Retourne les statistiques de base pour un owner.
    
    Args:
        owner_id: ID de l'owner
    
    Returns:
        {
            'total_leads': int,
            'leads_this_week': int,
            'verified_leads': int,
            'top_clients': [...],
            'leads_by_hour': [
                {
                    'hour': '2026-02-07T14:00:00Z',
                    'count': 15
                }
            ]
        }
    """
    from django.utils import timezone
    from datetime import timedelta
    
    queryset = OwnerClient.objects.filter(owner_id=owner_id)
    
    # Statistiques de base
    total = queryset.count()
    
    # Leads de cette semaine
    week_ago = timezone.now() - timedelta(days=7)
    this_week = queryset.filter(created_at__gte=week_ago).count()
    
    # Leads vérifiés
    verified = queryset.filter(is_verified=True).count()

    # ✅ Taux de retour (recognition_level > 2)
    returning_clients = queryset.filter(recognition_level__gt=2).count()
    return_rate = round((returning_clients / total * 100), 1) if total > 0 else 0.0
    
    # Top clients fidèles
    top_clients = _get_top_loyal_clients(queryset)
    
    # Distribution par heure (dernières 24h)
    leads_by_hour = _get_leads_by_hour(queryset)
    
    return {
        'total_leads': total,
        'leads_this_week': this_week,
        'verified_leads': verified,
        'return_rate': return_rate, 
        'top_clients': top_clients,
        'leads_by_hour': leads_by_hour
    }


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


def _get_leads_by_hour(queryset) -> List[Dict[str, Any]]:
    """
    Retourne le nombre de leads créés par heure (dernières 24h).
    
    Args:
        queryset: QuerySet filtré par owner
    
    Returns:
        Liste de {hour, count} triée chronologiquement
    """
    from django.utils import timezone
    from datetime import timedelta
    
    # Dernières 24 heures
    day_ago = timezone.now() - timedelta(hours=24)
    
    # Grouper par heure
    hourly_data = (
        queryset
        .filter(created_at__gte=day_ago)
        .annotate(hour=TruncHour('created_at'))
        .values('hour')
        .annotate(count=Count('id'))
        .order_by('hour')
    )
    
    return [
        {
            'hour': entry['hour'].isoformat() if entry['hour'] else None,
            'count': entry['count']
        }
        for entry in hourly_data
    ]