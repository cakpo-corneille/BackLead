# App Superadmin - Documentation Backend

## Vue d'ensemble

L'app `superadmin` fournit un dashboard KPIs temps reel et des outils de gestion pour le developpeur/operateur du SaaS WiFiLeads.

**Acces:** Reserve aux utilisateurs avec `is_superuser=True`.

---

## Models

### FeatureFlag
Gestion des feature flags pour le rollout progressif.

| Champ | Type | Description |
|-------|------|-------------|
| `key` | CharField | Identifiant unique (ex: new_dashboard) |
| `name` | CharField | Nom affiche |
| `is_enabled` | Boolean | Actif globalement |
| `rollout_percentage` | Integer | 0-100% pour rollout progressif |
| `enabled_for_plans` | M2M Plan | Plans autorises |
| `enabled_for_owners` | M2M Owner | Owners specifiques |

**Methode cle:**
```python
flag.is_enabled_for(owner)  # Verifie si le flag est actif pour cet owner
```

Ordre de verification:
1. Activation globale (`is_enabled=True`)
2. Owner dans `enabled_for_owners`
3. Plan de l'owner dans `enabled_for_plans`
4. Rollout progressif (hash deterministe sur owner_id)

### SystemConfig
Configuration systeme dynamique (key-value).

| Champ | Type | Description |
|-------|------|-------------|
| `key` | CharField | Cle unique |
| `value` | JSON | Valeur |
| `value_type` | Choice | string, integer, boolean, json |
| `updated_by` | FK User | Dernier modificateur |

**Methodes statiques:**
```python
SystemConfig.get('maintenance_mode', default=False)
SystemConfig.set('maintenance_mode', True, user=admin)
```

### AuditLog
Journal d'audit de toutes les actions superadmin.

| Champ | Type | Description |
|-------|------|-------------|
| `admin` | FK User | Administrateur |
| `action` | Choice | Type d'action |
| `target` | GenericFK | Objet cible |
| `target_repr` | CharField | Representation string |
| `details` | JSON | Details (avant/apres) |
| `ip_address` | IP | Adresse IP |
| `created_at` | DateTime | Horodatage |

**Actions disponibles:**
- `owner_viewed`, `owner_suspended`, `owner_activated`
- `owner_password_reset`, `owner_impersonated`
- `subscription_extended`, `subscription_upgraded`
- `flag_created`, `flag_updated`, `flag_deleted`, `flag_toggled`
- `config_updated`

### DailyMetrics
Metriques journalieres agregees pour l'historique.

| Categorie | Champs |
|-----------|--------|
| Owners | total_owners, new_owners, active_owners |
| Subscriptions | total, trial, active, churned, by_plan (JSON) |
| Revenue | mrr, arr, new_mrr, churned_mrr, revenue_today |
| Usage | total_leads, new_leads, widgets, sessions |
| Technique | api_calls, api_errors, celery_tasks |

### AlertRule
Regles d'alerte automatiques.

| Champ | Type | Description |
|-------|------|-------------|
| `metric` | Choice | churn_rate, error_rate, etc. |
| `operator` | Choice | gt, lt, eq, gte, lte |
| `threshold` | Decimal | Seuil de declenchement |
| `notify_email` | Email | Email de notification |
| `notify_webhook` | URL | URL webhook |

---

## Endpoints API

### KPIs (Metriques temps reel)

| Endpoint | Description |
|----------|-------------|
| `GET /api/v1/superadmin/kpis/realtime/` | KPIs temps reel |
| `GET /api/v1/superadmin/kpis/realtime/?refresh=true` | Force le recalcul |
| `GET /api/v1/superadmin/kpis/revenue/` | Details revenue + LTV |
| `GET /api/v1/superadmin/kpis/history/?days=30` | Historique N jours |

**Exemple reponse `/kpis/realtime/`:**
```json
{
    "timestamp": "2024-01-15T10:30:00Z",
    "owners": {
        "total": 150,
        "new_today": 3,
        "new_this_month": 25,
        "growth_rate": 12.5
    },
    "subscriptions": {
        "total": 145,
        "active": 80,
        "trial": 50,
        "past_due": 5,
        "by_plan": {"free": 50, "pro": 60, "business": 30},
        "trial_conversion_rate": 45.0
    },
    "revenue": {
        "mrr": 450000.00,
        "arr": 5400000.00,
        "revenue_today": 15000.00,
        "revenue_this_month": 380000.00,
        "arpu": 5625.00,
        "currency": "XOF"
    },
    "usage": {
        "leads": {"total": 12500, "today": 85, "this_month": 2100},
        "widgets": {"total": 200, "active": 180},
        "sessions": {"total": 50000, "active": 45, "today": 320}
    },
    "technical": {
        "status": "healthy",
        "checks": {
            "database": {"status": "ok"},
            "redis": {"status": "ok"},
            "celery": {"status": "ok", "tasks_count": 12}
        }
    }
}
```

### Sante Systeme

| Endpoint | Description |
|----------|-------------|
| `GET /api/v1/superadmin/health/` | Etat DB, Redis, Celery |

### Gestion des Owners

| Endpoint | Methode | Description |
|----------|---------|-------------|
| `GET /api/v1/superadmin/owners/` | GET | Liste avec filtres |
| `GET /api/v1/superadmin/owners/{id}/` | GET | Detail complet |
| `POST /api/v1/superadmin/owners/{id}/suspend/` | POST | Suspendre |
| `POST /api/v1/superadmin/owners/{id}/activate/` | POST | Reactiver |
| `POST /api/v1/superadmin/owners/{id}/reset-password/` | POST | Reset password |
| `POST /api/v1/superadmin/owners/{id}/impersonate/` | POST | Token impersonation |

**Filtres disponibles:**
- `?search=email|business_name`
- `?status=active|suspended`
- `?subscription=trial|active|past_due`
- `?plan=free|pro|business`
- `?ordering=-created_at`
- `?page=1&page_size=20`

### Gestion des Subscriptions

| Endpoint | Methode | Description |
|----------|---------|-------------|
| `GET /api/v1/superadmin/subscriptions/` | GET | Liste |
| `POST /api/v1/superadmin/subscriptions/{id}/extend/` | POST | Prolonger |
| `POST /api/v1/superadmin/subscriptions/{id}/upgrade/` | POST | Upgrade force |

**Exemple prolongation:**
```json
POST /api/v1/superadmin/subscriptions/1/extend/
{
    "days": 30,
    "reason": "Compensation pour bug"
}
```

### Feature Flags

| Endpoint | Methode | Description |
|----------|---------|-------------|
| `GET /api/v1/superadmin/flags/` | GET | Liste |
| `POST /api/v1/superadmin/flags/` | POST | Creer |
| `GET /api/v1/superadmin/flags/{key}/` | GET | Detail |
| `PUT /api/v1/superadmin/flags/{key}/` | PUT | Modifier |
| `DELETE /api/v1/superadmin/flags/{key}/` | DELETE | Supprimer |
| `POST /api/v1/superadmin/flags/{key}/toggle/` | POST | Toggle on/off |

**Exemple creation:**
```json
POST /api/v1/superadmin/flags/
{
    "key": "new_analytics_v2",
    "name": "Nouveau dashboard analytics",
    "description": "Version 2 du module analytics",
    "is_enabled": false,
    "rollout_percentage": 10,
    "enabled_for_plans": [2, 3]  // Pro et Business
}
```

### Configuration Systeme

| Endpoint | Methode | Description |
|----------|---------|-------------|
| `GET /api/v1/superadmin/config/` | GET | Liste |
| `PUT /api/v1/superadmin/config/{key}/` | PUT | Modifier |

### Audit Logs

| Endpoint | Methode | Description |
|----------|---------|-------------|
| `GET /api/v1/superadmin/audit-logs/` | GET | Liste (lecture seule) |

**Filtres:**
- `?action=owner_suspended`
- `?admin=1`
- `?from=2024-01-01&to=2024-01-31`

### Alertes

| Endpoint | Methode | Description |
|----------|---------|-------------|
| `GET /api/v1/superadmin/alerts/` | GET | Liste regles |
| `POST /api/v1/superadmin/alerts/` | POST | Creer regle |
| `PUT /api/v1/superadmin/alerts/{id}/` | PUT | Modifier |
| `DELETE /api/v1/superadmin/alerts/{id}/` | DELETE | Supprimer |

---

## Services

### KPIService
Calcul des KPIs avec cache Redis.

```python
from superadmin.services import KPIService

# KPIs temps reel (cache 30s)
kpis = KPIService.get_realtime_kpis()

# Revenue detaille
breakdown = KPIService.get_revenue_breakdown()

# Metriques calculees
churn = KPIService.calculate_churn_rate(days=30)
ltv = KPIService.calculate_ltv()

# Sante systeme
health = KPIService.get_system_health()
```

### OwnerManagementService
Actions sur les owners.

```python
from superadmin.services import OwnerManagementService

# Suspendre
OwnerManagementService.suspend_owner(owner, admin, reason="Fraude", request=request)

# Reactiver
OwnerManagementService.activate_owner(owner, admin, request=request)

# Reset password
OwnerManagementService.reset_owner_password(owner, admin, request=request)

# Impersonation (attention: action sensible)
tokens = OwnerManagementService.generate_impersonation_token(owner, admin, request=request)
# Retourne {'access': ..., 'refresh': ..., 'expires_in': 3600}
```

---

## Taches Celery

| Tache | Frequence | Description |
|-------|-----------|-------------|
| `cache_realtime_kpis` | 30s | Met en cache les KPIs |
| `check_alert_rules` | 5 min | Verifie les regles d'alerte |
| `calculate_daily_metrics` | 24h | Calcule les metriques du jour |
| `cleanup_old_audit_logs` | 30j | Nettoie les logs > 1 an |

---

## Permission

```python
from superadmin.permissions import IsSuperAdmin

class MyView(APIView):
    permission_classes = [IsSuperAdmin]
```

La permission verifie `request.user.is_superuser == True`.

---

## Audit automatique

Toutes les actions sont automatiquement loguees:

```python
from superadmin.models import AuditLog

# Log manuel
AuditLog.log(
    admin=request.user,
    action=AuditLog.Action.OWNER_SUSPENDED,
    target=owner,
    details={'reason': 'Fraude'},
    request=request  # Pour IP et user-agent
)
```

---

## Utilisation des Feature Flags

Dans le code de l'application:

```python
from superadmin.models import FeatureFlag

def my_view(request):
    owner = request.user.owner_profile
    
    # Verifier un flag
    flag = FeatureFlag.objects.filter(key='new_analytics').first()
    if flag and flag.is_enabled_for(owner):
        # Afficher la nouvelle version
        return render_new_analytics()
    else:
        return render_old_analytics()
```

Ou via un middleware/decorator:

```python
def feature_flag_required(flag_key):
    def decorator(view_func):
        def wrapper(request, *args, **kwargs):
            owner = getattr(request.user, 'owner_profile', None)
            flag = FeatureFlag.objects.filter(key=flag_key).first()
            
            if not flag or not flag.is_enabled_for(owner):
                return JsonResponse({'error': 'Feature not available'}, status=403)
            
            return view_func(request, *args, **kwargs)
        return wrapper
    return decorator

@feature_flag_required('beta_export')
def export_view(request):
    ...
```
