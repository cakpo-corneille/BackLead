# App Subscriptions - Documentation Frontend

## Vue d'ensemble

Cette documentation decrit comment integrer l'API Subscriptions dans une application frontend (React, Vue, etc.).

---

## Authentification

Toutes les requetes (sauf `/plans/`) necessitent un token JWT dans le header:

```
Authorization: Bearer <access_token>
```

---

## Endpoints et Exemples

### 1. Lister les plans disponibles

```javascript
// GET /api/v1/plans/
const response = await fetch('/api/v1/plans/');
const plans = await response.json();

// Response
[
    {
        "id": 1,
        "name": "Free",
        "slug": "free",
        "price_monthly": "0.00",
        "price_yearly": "0.00",
        "max_widgets": 1,
        "max_leads_per_month": 50,
        "max_routers": 1,
        "features": {"analytics": false, "export_csv": false},
        "trial_days": 0,
        "is_popular": false
    },
    {
        "id": 2,
        "name": "Pro",
        "slug": "pro",
        "price_monthly": "5000.00",
        "price_yearly": "50000.00",
        "max_widgets": 5,
        "max_leads_per_month": 500,
        "max_routers": 3,
        "features": {"analytics": true, "export_csv": true, "api_access": true},
        "trial_days": 14,
        "is_popular": true
    }
]
```

### 2. Obtenir l'abonnement actuel

```javascript
// GET /api/v1/subscription/
const response = await fetch('/api/v1/subscription/', {
    headers: { 'Authorization': `Bearer ${token}` }
});

// Response
{
    "id": 1,
    "plan": {
        "id": 2,
        "name": "Pro",
        "slug": "pro",
        ...
    },
    "status": "active",
    "billing_cycle": "monthly",
    "current_period_start": "2024-01-01T00:00:00Z",
    "current_period_end": "2024-02-01T00:00:00Z",
    "leads_used": 45,
    "days_until_renewal": 15,
    "current_price": "5000.00",
    "usage_percentage": 9.0
}
```

### 3. Resume pour le dashboard

```javascript
// GET /api/v1/subscription/summary/
const response = await fetch('/api/v1/subscription/summary/', {
    headers: { 'Authorization': `Bearer ${token}` }
});

// Response
{
    "status": "active",
    "plan_name": "Pro",
    "plan_slug": "pro",
    "billing_cycle": "monthly",
    "current_period_end": "2024-02-01T00:00:00Z",
    "days_until_renewal": 15,
    "leads_used": 45,
    "leads_remaining": 455,
    "can_create_lead": true
}
```

### 4. Changer de plan (Upgrade)

```javascript
// POST /api/v1/subscription/upgrade/
const response = await fetch('/api/v1/subscription/upgrade/', {
    method: 'POST',
    headers: {
        'Authorization': `Bearer ${token}`,
        'Content-Type': 'application/json'
    },
    body: JSON.stringify({
        plan_id: 3,
        billing_cycle: 'yearly'  // optionnel
    })
});

// Response
{
    "detail": "Votre abonnement a ete mis a jour vers Business.",
    "subscription": { ... }
}
```

### 5. Annuler l'abonnement

```javascript
// POST /api/v1/subscription/cancel/
const response = await fetch('/api/v1/subscription/cancel/', {
    method: 'POST',
    headers: {
        'Authorization': `Bearer ${token}`,
        'Content-Type': 'application/json'
    },
    body: JSON.stringify({
        reason: "Trop cher",  // optionnel
        confirm: true
    })
});

// Response
{
    "detail": "Votre abonnement a ete annule. Il restera actif jusqu'a la fin de la periode en cours.",
    "current_period_end": "2024-02-01T00:00:00Z"
}
```

---

## Paiements Mobile Money

### 1. Initier un paiement

```javascript
// POST /api/v1/payments/initiate/
const response = await fetch('/api/v1/payments/initiate/', {
    method: 'POST',
    headers: {
        'Authorization': `Bearer ${token}`,
        'Content-Type': 'application/json'
    },
    body: JSON.stringify({
        provider: 'mtn_momo',  // ou 'moov_money'
        phone_number: '90123456'
    })
});

// Response (201 Created)
{
    "detail": "Paiement initie. Veuillez confirmer sur votre telephone.",
    "payment": {
        "id": 1,
        "uuid": "abc123...",
        "amount": "5000.00",
        "currency": "XOF",
        "status": "processing",
        "status_display": "En cours",
        "provider": "mtn_momo",
        "provider_display": "MTN Mobile Money",
        "phone_number": "22990123456"
    }
}
```

### 2. Verifier le statut d'un paiement

```javascript
// GET /api/v1/payments/{id}/check_status/
const response = await fetch(`/api/v1/payments/${paymentId}/check_status/`, {
    headers: { 'Authorization': `Bearer ${token}` }
});

// Response
{
    "status": "completed",  // ou 'pending', 'processing', 'failed'
    "status_display": "Complete",
    "completed_at": "2024-01-15T10:30:00Z"
}
```

### 3. Historique des paiements

```javascript
// GET /api/v1/payments/history/
const response = await fetch('/api/v1/payments/history/', {
    headers: { 'Authorization': `Bearer ${token}` }
});

// Response
[
    {
        "id": 2,
        "uuid": "...",
        "amount": "5000.00",
        "status": "completed",
        "provider": "mtn_momo",
        "phone_number": "22990123456",
        "created_at": "2024-01-15T10:00:00Z",
        "completed_at": "2024-01-15T10:30:00Z"
    },
    ...
]
```

---

## Factures

### 1. Liste des factures

```javascript
// GET /api/v1/invoices/
const response = await fetch('/api/v1/invoices/', {
    headers: { 'Authorization': `Bearer ${token}` }
});

// Response
[
    {
        "id": 1,
        "invoice_number": "WFL-2024-0001",
        "amount": "5000.00",
        "currency": "XOF",
        "period_start": "2024-01-01T00:00:00Z",
        "period_end": "2024-02-01T00:00:00Z",
        "is_paid": true,
        "paid_at": "2024-01-01T10:00:00Z",
        "plan_name": "Pro"
    }
]
```

---

## Flux de paiement recommande

```
1. Utilisateur choisit un plan
   └── GET /api/v1/plans/

2. Afficher formulaire de paiement
   └── Choix: MTN MoMo ou Moov Money
   └── Saisie numero telephone

3. Initier le paiement
   └── POST /api/v1/payments/initiate/
   └── Afficher message "Confirmez sur votre telephone"

4. Polling du statut (toutes les 5s)
   └── GET /api/v1/payments/{id}/check_status/
   └── Si 'completed' -> Succes!
   └── Si 'failed' -> Afficher erreur
   └── Si toujours 'processing' apres 2min -> Proposer de reessayer

5. Succes: Rafraichir les donnees subscription
   └── GET /api/v1/subscription/
```

---

## Gestion des erreurs

```javascript
// Erreurs communes
{
    "detail": "Aucun abonnement trouve."
}  // 404 - Owner sans subscription

{
    "detail": "Ce numero n'est pas un numero MTN valide."
}  // 400 - Validation numero

{
    "detail": "Limite de leads atteinte pour ce mois."
}  // 403 - Quota depasse
```

---

## Types TypeScript

```typescript
interface Plan {
    id: number;
    name: string;
    slug: string;
    description: string;
    price_monthly: string;
    price_yearly: string;
    currency: string;
    max_widgets: number;
    max_leads_per_month: number;
    max_routers: number;
    features: Record<string, boolean>;
    trial_days: number;
    is_popular: boolean;
}

interface Subscription {
    id: number;
    plan: Plan;
    status: 'trial' | 'active' | 'past_due' | 'cancelled' | 'expired';
    billing_cycle: 'monthly' | 'yearly';
    current_period_start: string;
    current_period_end: string;
    leads_used: number;
    days_until_renewal: number;
    current_price: string;
    usage_percentage: number;
}

interface Payment {
    id: number;
    uuid: string;
    amount: string;
    currency: string;
    status: 'pending' | 'processing' | 'completed' | 'failed';
    provider: 'mtn_momo' | 'moov_money' | 'manual';
    phone_number: string;
    created_at: string;
    completed_at: string | null;
}

interface Invoice {
    id: number;
    invoice_number: string;
    amount: string;
    currency: string;
    period_start: string;
    period_end: string;
    is_paid: boolean;
    paid_at: string | null;
    pdf_url: string | null;
    plan_name: string;
}
```
