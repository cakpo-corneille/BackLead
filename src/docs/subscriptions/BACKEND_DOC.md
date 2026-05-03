# App Subscriptions - Documentation Backend

## Vue d'ensemble

L'app `subscriptions` gere les abonnements des owners avec integration Mobile Money (MTN MoMo et Moov Money) pour le Benin.

## Models

### Plan
Plans d'abonnement disponibles (Free, Pro, Business).

| Champ | Type | Description |
|-------|------|-------------|
| `name` | CharField | Nom du plan |
| `slug` | SlugField | Identifiant unique |
| `price_monthly` | Decimal | Prix mensuel en XOF |
| `price_yearly` | Decimal | Prix annuel en XOF |
| `max_widgets` | Integer | Limite de widgets |
| `max_leads_per_month` | Integer | Limite de leads/mois |
| `max_routers` | Integer | Limite de routeurs |
| `features` | JSON | Fonctionnalites du plan |
| `trial_days` | Integer | Duree de la periode d'essai |

### Subscription
Abonnement d'un Owner a un Plan.

| Champ | Type | Description |
|-------|------|-------------|
| `owner` | FK Owner | Proprietaire (OneToOne) |
| `plan` | FK Plan | Plan choisi |
| `status` | Choice | trial, active, past_due, cancelled, expired |
| `billing_cycle` | Choice | monthly, yearly |
| `current_period_start` | DateTime | Debut periode courante |
| `current_period_end` | DateTime | Fin periode courante |
| `leads_used` | Integer | Leads utilises cette periode |

**Methodes importantes:**
- `can_create_lead()` - Verifie si l'owner peut creer un lead
- `can_create_widget(count)` - Verifie limite widgets
- `can_create_router(count)` - Verifie limite routeurs
- `has_feature(key)` - Verifie acces a une fonctionnalite
- `renew()` - Renouvelle l'abonnement
- `cancel(reason)` - Annule l'abonnement

### Payment
Historique des paiements Mobile Money.

| Champ | Type | Description |
|-------|------|-------------|
| `uuid` | UUID | Identifiant unique |
| `subscription` | FK Subscription | Abonnement associe |
| `amount` | Decimal | Montant en XOF |
| `provider` | Choice | mtn_momo, moov_money, manual |
| `phone_number` | CharField | Numero utilise |
| `status` | Choice | pending, processing, completed, failed |
| `external_id` | CharField | ID transaction operateur |

### Invoice
Factures generees automatiquement.

| Champ | Type | Description |
|-------|------|-------------|
| `invoice_number` | CharField | Numero unique (WFL-YYYY-NNNN) |
| `subscription` | FK Subscription | Abonnement |
| `amount` | Decimal | Montant |
| `period_start/end` | DateTime | Periode couverte |
| `is_paid` | Boolean | Etat paiement |

---

## Endpoints API

### Plans (Public)

| Endpoint | Methode | Description |
|----------|---------|-------------|
| `GET /api/v1/plans/` | GET | Liste des plans actifs |
| `GET /api/v1/plans/{id}/` | GET | Detail d'un plan |

### Subscription (Authentifie)

| Endpoint | Methode | Description |
|----------|---------|-------------|
| `GET /api/v1/subscription/` | GET | Abonnement actuel |
| `GET /api/v1/subscription/summary/` | GET | Resume pour dashboard |
| `POST /api/v1/subscription/upgrade/` | POST | Changer de plan |
| `POST /api/v1/subscription/cancel/` | POST | Annuler |

**Exemple upgrade:**
```json
POST /api/v1/subscription/upgrade/
{
    "plan_id": 2,
    "billing_cycle": "yearly"
}
```

### Payments (Authentifie)

| Endpoint | Methode | Description |
|----------|---------|-------------|
| `POST /api/v1/payments/initiate/` | POST | Initier paiement Mobile Money |
| `GET /api/v1/payments/history/` | GET | Historique paiements |
| `GET /api/v1/payments/{id}/` | GET | Detail paiement |
| `GET /api/v1/payments/{id}/check_status/` | GET | Verifier statut |

**Exemple initiation paiement:**
```json
POST /api/v1/payments/initiate/
{
    "provider": "mtn_momo",
    "phone_number": "90123456"
}

Response:
{
    "detail": "Paiement initie. Veuillez confirmer sur votre telephone.",
    "payment": {
        "id": 1,
        "uuid": "...",
        "amount": "5000.00",
        "status": "processing",
        "provider": "mtn_momo"
    }
}
```

### Webhooks (Mobile Money Callbacks)

| Endpoint | Methode | Description |
|----------|---------|-------------|
| `POST /api/v1/payments/callback/mtn/` | POST | Callback MTN MoMo |
| `POST /api/v1/payments/callback/moov/` | POST | Callback Moov Money |

Ces endpoints sont appeles par les operateurs pour notifier les changements de statut des transactions.

### Invoices (Authentifie)

| Endpoint | Methode | Description |
|----------|---------|-------------|
| `GET /api/v1/invoices/` | GET | Liste factures |
| `GET /api/v1/invoices/{id}/` | GET | Detail facture |
| `GET /api/v1/invoices/{id}/download/` | GET | URL PDF |

---

## Services

### MobileMoneyService
Interface abstraite pour les paiements Mobile Money.

```python
from subscriptions.services import get_mobile_money_service

service = get_mobile_money_service('mtn_momo')
result = service.initiate_payment(
    phone_number='22990123456',
    amount=Decimal('5000'),
    reference='WFL-PAY-001',
    description='Abonnement WiFiLeads Pro'
)
```

### SubscriptionService
Gestion du cycle de vie des abonnements.

```python
from subscriptions.services import SubscriptionService

# Creer un abonnement
subscription = SubscriptionService.create_subscription(owner, plan, 'monthly')

# Upgrade
subscription = SubscriptionService.upgrade_plan(subscription, new_plan)

# Traiter paiement reussi
SubscriptionService.process_successful_payment(payment)
```

### PaymentService
Gestion des paiements.

```python
from subscriptions.services import PaymentService

# Initier un paiement
payment = PaymentService.initiate_payment(
    subscription=subscription,
    provider='mtn_momo',
    phone_number='22990123456'
)

# Verifier statut
PaymentService.check_payment_status(payment)
```

---

## Taches Celery

| Tache | Frequence | Description |
|-------|-----------|-------------|
| `check_pending_payments` | 2 min | Verifie les paiements en attente |
| `expire_old_pending_payments` | 15 min | Annule les paiements > 1h |
| `expire_trial_subscriptions` | 6h | Expire les essais termines |
| `suspend_overdue_subscriptions` | 12h | Suspend les abonnements non payes |
| `send_payment_reminders` | 24h | Rappels avant expiration |
| `process_subscription_renewals` | 24h | Traite les renouvellements |

---

## Configuration

Variables d'environnement requises:

```bash
# MTN Mobile Money
MTN_MOMO_API_KEY=your_api_key
MTN_MOMO_API_SECRET=your_api_secret
MTN_MOMO_SUBSCRIPTION_KEY=your_subscription_key
MTN_MOMO_ENVIRONMENT=sandbox|production

# Moov Money
MOOV_MONEY_API_KEY=your_api_key
MOOV_MONEY_MERCHANT_ID=your_merchant_id
MOOV_MONEY_ENVIRONMENT=sandbox|production
```

---

## Integration avec les autres apps

### Verification des limites dans core_data

```python
# Dans LeadViewSet.create()
subscription = owner.subscription
if not subscription.can_create_lead():
    raise PermissionDenied("Limite de leads atteinte pour ce mois.")

# Apres creation du lead
subscription.increment_lead_usage()
```

### Verification dans tracking

```python
# Dans MikroTikRouterViewSet.create()
subscription = owner.subscription
current_count = owner.routers.count()
if not subscription.can_create_router(current_count):
    raise PermissionDenied("Limite de routeurs atteinte pour votre plan.")
```

---

## Signal: Creation automatique d'abonnement

Quand un Owner est cree, un abonnement Free/Trial est automatiquement cree:

```python
# subscriptions/signals.py
@receiver(post_save, sender='accounts.Owner')
def create_default_subscription(sender, instance, created, **kwargs):
    if created:
        free_plan = Plan.objects.filter(slug='free').first()
        Subscription.objects.create(owner=instance, plan=free_plan)
```
