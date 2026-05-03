# App Superadmin - Documentation Frontend

## Vue d'ensemble

Cette documentation decrit l'integration du dashboard Superadmin dans une application frontend.

**Important:** Tous les endpoints necessitent un token JWT d'un utilisateur `is_superuser=True`.

---

## Authentification

```javascript
const headers = {
    'Authorization': `Bearer ${superadminToken}`,
    'Content-Type': 'application/json'
};
```

---

## Dashboard KPIs

### KPIs Temps Reel

```javascript
// GET /api/v1/superadmin/kpis/realtime/
const response = await fetch('/api/v1/superadmin/kpis/realtime/', { headers });
const kpis = await response.json();

// Response
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
            "database": {"status": "ok", "message": "Connected"},
            "redis": {"status": "ok", "message": "Connected"},
            "celery": {"status": "ok", "tasks_count": 12}
        }
    }
}
```

### Revenue et LTV

```javascript
// GET /api/v1/superadmin/kpis/revenue/
const response = await fetch('/api/v1/superadmin/kpis/revenue/', { headers });

// Response
{
    "revenue": {
        "mrr": 450000.00,
        "arr": 5400000.00,
        "revenue_today": 15000.00,
        "revenue_this_month": 380000.00,
        "arpu": 5625.00,
        "currency": "XOF"
    },
    "breakdown": {
        "by_plan": {
            "Pro": {"count": 60, "mrr": 300000.00},
            "Business": {"count": 30, "mrr": 450000.00}
        },
        "by_cycle": {
            "monthly": 500000.00,
            "yearly": 250000.00
        },
        "total_mrr": 750000.00
    },
    "churn_rate_30d": 3.5,
    "ltv": 128571.43
}
```

### Historique pour graphiques

```javascript
// GET /api/v1/superadmin/kpis/history/?days=30
const response = await fetch('/api/v1/superadmin/kpis/history/?days=30', { headers });

// Response
{
    "period_days": 30,
    "data": [
        {
            "date": "2024-01-01",
            "total_owners": 120,
            "new_owners": 5,
            "active_subscriptions": 70,
            "mrr": 400000.00,
            "total_leads": 10000,
            "new_leads": 150
        },
        // ... 29 autres jours
    ]
}
```

---

## Gestion des Owners

### Liste avec filtres

```javascript
// GET /api/v1/superadmin/owners/?status=active&plan=pro&page=1
const params = new URLSearchParams({
    status: 'active',
    plan: 'pro',
    search: 'john@example.com',
    page: 1,
    page_size: 20,
    ordering: '-created_at'
});

const response = await fetch(`/api/v1/superadmin/owners/?${params}`, { headers });

// Response
{
    "count": 150,
    "page": 1,
    "page_size": 20,
    "results": [
        {
            "id": 1,
            "email": "john@example.com",
            "business_name": "John's Cafe",
            "phone": "+22990123456",
            "is_active": true,
            "subscription_status": "active",
            "subscription_plan": "Pro",
            "leads_count": 245,
            "widgets_count": 3,
            "created_at": "2024-01-01T00:00:00Z"
        },
        // ...
    ]
}
```

### Detail d'un Owner

```javascript
// GET /api/v1/superadmin/owners/1/
const response = await fetch('/api/v1/superadmin/owners/1/', { headers });

// Response
{
    "id": 1,
    "email": "john@example.com",
    "business_name": "John's Cafe",
    "phone": "+22990123456",
    "is_active": true,
    "last_login": "2024-01-15T08:00:00Z",
    "date_joined": "2024-01-01T00:00:00Z",
    "subscription": {
        "id": 1,
        "plan": {"id": 2, "name": "Pro", "slug": "pro"},
        "status": "active",
        "billing_cycle": "monthly",
        "current_period_end": "2024-02-01T00:00:00Z",
        "leads_used": 45
    },
    "recent_leads": [
        {"id": 100, "email": "lead@test.com", "created_at": "2024-01-14T12:00:00Z"}
    ],
    "recent_payments": [
        {"id": 50, "amount": "5000.00", "status": "completed", "created_at": "2024-01-01T10:00:00Z"}
    ]
}
```

### Actions sur les Owners

```javascript
// Suspendre
await fetch('/api/v1/superadmin/owners/1/suspend/', {
    method: 'POST',
    headers,
    body: JSON.stringify({ reason: "Violation des CGU" })
});

// Reactiver
await fetch('/api/v1/superadmin/owners/1/activate/', {
    method: 'POST',
    headers
});

// Reset password
await fetch('/api/v1/superadmin/owners/1/reset-password/', {
    method: 'POST',
    headers
});

// Impersonation (se connecter en tant que)
const response = await fetch('/api/v1/superadmin/owners/1/impersonate/', {
    method: 'POST',
    headers
});
const { tokens } = await response.json();
// tokens = { access: "...", refresh: "...", expires_in: 3600 }
```

---

## Feature Flags

### Liste

```javascript
// GET /api/v1/superadmin/flags/
const response = await fetch('/api/v1/superadmin/flags/', { headers });

// Response
[
    {
        "id": 1,
        "key": "new_analytics_v2",
        "name": "Nouveau Analytics",
        "description": "Version 2 du module analytics",
        "is_enabled": false,
        "rollout_percentage": 25,
        "enabled_plans_count": 2,
        "enabled_owners_count": 5
    }
]
```

### Creer

```javascript
await fetch('/api/v1/superadmin/flags/', {
    method: 'POST',
    headers,
    body: JSON.stringify({
        key: "beta_export",
        name: "Export Beta",
        description: "Nouvelle fonction d'export",
        is_enabled: false,
        rollout_percentage: 10,
        enabled_for_plans: [2, 3]  // IDs des plans
    })
});
```

### Toggle

```javascript
// POST /api/v1/superadmin/flags/new_analytics_v2/toggle/
const response = await fetch('/api/v1/superadmin/flags/new_analytics_v2/toggle/', {
    method: 'POST',
    headers
});

// Response
{
    "key": "new_analytics_v2",
    "is_enabled": true,
    "message": "Flag active"
}
```

---

## Audit Logs

```javascript
// GET /api/v1/superadmin/audit-logs/?action=owner_suspended&from=2024-01-01
const response = await fetch('/api/v1/superadmin/audit-logs/?action=owner_suspended', { headers });

// Response
[
    {
        "id": 1,
        "admin_email": "admin@wifileads.com",
        "action": "owner_suspended",
        "action_display": "Owner suspendu",
        "target_repr": "John's Cafe",
        "details": {"reason": "Violation des CGU"},
        "ip_address": "192.168.1.1",
        "created_at": "2024-01-15T10:00:00Z"
    }
]
```

---

## Sante Systeme

```javascript
// GET /api/v1/superadmin/health/
const response = await fetch('/api/v1/superadmin/health/', { headers });

// Response
{
    "status": "healthy",  // ou "degraded"
    "checks": {
        "database": {"status": "ok", "message": "Connected"},
        "redis": {"status": "ok", "message": "Connected"},
        "celery": {"status": "ok", "tasks_count": 12, "message": "12 periodic tasks"}
    }
}
```

---

## Types TypeScript

```typescript
interface RealtimeKPIs {
    timestamp: string;
    owners: {
        total: number;
        new_today: number;
        new_this_month: number;
        growth_rate: number;
    };
    subscriptions: {
        total: number;
        active: number;
        trial: number;
        past_due: number;
        cancelled: number;
        by_plan: Record<string, number>;
        trial_conversion_rate: number;
    };
    revenue: {
        mrr: number;
        arr: number;
        revenue_today: number;
        revenue_this_month: number;
        arpu: number;
        currency: string;
    };
    usage: {
        leads: { total: number; today: number; this_month: number };
        widgets: { total: number; active: number };
        sessions: { total: number; active: number; today: number };
    };
    technical: SystemHealth;
}

interface SystemHealth {
    status: 'healthy' | 'degraded';
    checks: {
        database: HealthCheck;
        redis: HealthCheck;
        celery: HealthCheck;
    };
}

interface HealthCheck {
    status: 'ok' | 'warning' | 'error';
    message: string;
    tasks_count?: number;
}

interface OwnerListItem {
    id: number;
    email: string;
    business_name: string;
    phone: string;
    is_active: boolean;
    subscription_status: string;
    subscription_plan: string;
    leads_count: number;
    widgets_count: number;
    created_at: string;
}

interface FeatureFlag {
    id: number;
    key: string;
    name: string;
    description: string;
    is_enabled: boolean;
    rollout_percentage: number;
    enabled_plans_count: number;
    enabled_owners_count: number;
    created_at: string;
    updated_at: string;
}

interface AuditLog {
    id: number;
    admin_email: string;
    action: string;
    action_display: string;
    target_repr: string;
    details: Record<string, any>;
    ip_address: string;
    created_at: string;
}
```

---

## Bonnes pratiques

### Polling des KPIs

```javascript
// Polling toutes les 30 secondes
useEffect(() => {
    const fetchKPIs = async () => {
        const response = await fetch('/api/v1/superadmin/kpis/realtime/', { headers });
        setKpis(await response.json());
    };
    
    fetchKPIs();
    const interval = setInterval(fetchKPIs, 30000);
    
    return () => clearInterval(interval);
}, []);
```

### Gestion des erreurs

```javascript
try {
    const response = await fetch('/api/v1/superadmin/owners/1/suspend/', {
        method: 'POST',
        headers,
        body: JSON.stringify({ reason })
    });
    
    if (!response.ok) {
        if (response.status === 403) {
            throw new Error("Acces refuse - droits superadmin requis");
        }
        if (response.status === 400) {
            const data = await response.json();
            throw new Error(data.detail);
        }
    }
    
    // Succes
} catch (error) {
    showNotification('error', error.message);
}
```
