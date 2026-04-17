# WiFi Marketing Platform - Documentation Backend

**Version :** 3.0
**Date :** Avril 2026
**Public :** Développeurs Backend, DevOps, Maintenance

---

## Architecture générale

L'application `core_data` est le cœur du système. Elle gère :
- La configuration du widget de collecte (FormSchema)
- Les leads captifs (OwnerClient)
- Les analytics dashboard
- Le flux du portail captif (soumission, vérification OTP, redirection)

---

## Modèles

### FormSchema

Schéma de formulaire d'un propriétaire WiFi.

```python
class FormSchema(DirtyFieldsMixin, models.Model):
    owner           = OneToOneField(User, related_name='form_schema')
    public_key      = UUIDField(default=uuid.uuid4, unique=True, editable=False)
    name            = CharField(max_length=255, default='Mon Formulaire')
    title           = CharField(max_length=255, blank=True)
    description     = TextField(blank=True)
    logo            = ImageField(upload_to='logos/schema', blank=True)
    button_label    = CharField(max_length=100, blank=True)
    schema          = JSONField(default=dict)
    double_opt_enable = BooleanField(default=False)
    enable          = BooleanField(default=True)
    version         = PositiveIntegerField(default=1)
    created_at      = DateTimeField(auto_now_add=True)
    updated_at      = DateTimeField(auto_now=True)
```

**Champ `schema` (structure JSON) :**

```json
{
  "fields": [
    {
      "name": "nom",
      "label": "Nom complet",
      "type": "text",
      "required": true
    },
    {
      "name": "email",
      "label": "Adresse email",
      "type": "email",
      "required": true
    },
    {
      "name": "phone",
      "label": "Téléphone",
      "type": "phone",
      "required": false
    },
    {
      "name": "source",
      "label": "Comment nous avez-vous connu ?",
      "type": "choice",
      "choices": ["Facebook", "Instagram", "Google", "Autre"],
      "required": false
    }
  ]
}
```

**Types de champs supportés :** `text`, `email`, `phone`, `choice`, `checkbox`, `date`, `textarea`

**Méthode `save()` — Gestion des versions :**
La version est auto-incrémentée si des champs structurels changent (`schema`, `double_opt_enable`).

**Signal post_save sur User :**
Crée automatiquement un FormSchema vide à la création d'un compte.

---

### OwnerClient

Représente un client capturé via le widget.

```python
class OwnerClient(models.Model):
    owner             = ForeignKey(User, related_name='clients')
    mac_address       = CharField(max_length=17, blank=True)
    client_token      = UUIDField(default=uuid.uuid4, unique=True)
    email             = EmailField(null=True, blank=True)
    phone             = CharField(max_length=20, null=True, blank=True)
    payload           = JSONField(default=dict)
    recognition_level = PositiveIntegerField(default=0)
    is_verified       = BooleanField(default=False)
    tags              = JSONField(default=list, blank=True)
    notes             = TextField(null=True, blank=True)
    created_at        = DateTimeField(auto_now_add=True)
    updated_at        = DateTimeField(auto_now=True)
    last_seen         = DateTimeField(default=timezone.now)

    class Meta:
        unique_together = [
            ('owner', 'mac_address'),
            ('owner', 'client_token'),
        ]
```

**Champ `tags` :** liste JSON de chaînes (ex. `["VIP", "Fidèle"]`)

**Champ `notes` :** texte libre pour qualifier le lead

**Champ `recognition_level` :**
- `0–4` → Inconnu
- `5–19` → Visiteur
- `20–49` → Régulier
- `50+` → Fidèle

---

## Services métier

### verification_services.py

#### detect_existing_client(mac, token, phone)

Détecte un client existant dans cet ordre de priorité :
1. MAC address (si fournie)
2. Client token (si fourni)
3. Téléphone (si fourni)

> **Note :** La détection par email n'est PAS implémentée.

**Returns :** `OwnerClient | None`

---

#### submit_form(owner_id, payload, mac, token)

Traite la soumission du formulaire widget.

**Flow :**
1. Récupérer le schéma actif du propriétaire
2. Valider le payload selon le schéma
3. Détecter client existant (MAC > token > phone)
4. Créer ou mettre à jour le lead
5. Incrémenter `recognition_level`
6. Mettre à jour `last_seen`

**Returns :**
```python
{
    'client': OwnerClient,
    'client_token': str,
    'is_new': bool,
    'double_opt_required': bool,  # True si double_opt_enable + email présent
}
```

---

#### send_verification_code(client, channel)

Envoie un code OTP pour le double opt-in.

**Canaux :** `'email'` ou `'sms'`

**Cache key :** `double_opt_{client.id}` (TTL `DOUBLE_OPT_TTL = 300 s` / 5 min)

---

#### verify_client_code(client, code)

Vérifie le code double opt-in et positionne `is_verified=True` si valide.

**Returns :** `(success: bool, error_message: str)`

---

### portal_services.py

#### get_portal_url(client_token, owner_id)

Renvoie l'URL de redirection finale du portail captif après validation.

---

### dashboard_services.py

Analytics pour le tableau de bord propriétaire.

**Cache :** Toutes les métriques sont mises en cache pendant **3600 s** (1 heure).

**Fonctions disponibles :**

```python
get_leads_overview(owner)         # Vue globale leads
get_leads_by_day(owner, days)     # Courbe temporelle
get_recognition_breakdown(owner)  # Distribution fidélité
get_verification_rate(owner)      # Taux de vérification double opt-in
get_top_fields(owner)             # Champs les plus remplis
```

---

### messages_services.py

Envoi de messages marketing aux leads.

```python
send_bulk_message(owner, recipient_list, content, channel)
# channel: 'email' | 'sms'
```

---

## ViewSets & Endpoints

### FormSchemaViewSet

**Base :** `/api/v1/schema/`

| Endpoint              | Méthode  | Auth | Description                        |
|-----------------------|----------|------|------------------------------------|
| `/`                   | GET      | Auth | Récupérer son schéma               |
| `/`                   | PATCH    | Auth | Mettre à jour le schéma            |
| `{public_key}/public/`| GET      | —    | Schéma public (pour le widget)     |

---

### LeadViewSet

**Base :** `/api/v1/leads/`

| Endpoint         | Méthode        | Auth | Description                              |
|------------------|----------------|------|------------------------------------------|
| `/`              | GET            | Auth | Liste des leads (filtres, pagination)    |
| `{id}/`          | GET            | Auth | Détail d'un lead                         |
| `{id}/`          | PATCH          | Auth | Modifier tags et notes d'un lead         |
| `{id}/`          | DELETE         | Auth | Supprimer un lead                        |
| `stats/`         | GET            | Auth | Statistiques agrégées                    |
| `export/`        | GET            | Auth | Export CSV                               |

**Filtres disponibles :**
- `?is_verified=true|false`
- `?search=<terme>` (email, phone, payload)
- `?page=<n>&page_size=<n>`
- `?ordering=created_at|-created_at|last_seen`
- `?date_from=YYYY-MM-DD&date_to=YYYY-MM-DD`

---

### AnalyticsViewSet

**Base :** `/api/v1/analytics/`

| Endpoint              | Méthode | Auth | Description                    |
|-----------------------|---------|------|--------------------------------|
| `overview/`           | GET     | Auth | Vue globale dashboard          |
| `leads-by-day/`       | GET     | Auth | Leads par jour (30j par défaut)|
| `recognition/`        | GET     | Auth | Distribution fidélité          |
| `verification-rate/`  | GET     | Auth | Taux double opt-in             |

---

### PortalViewSet

**Base :** `/api/v1/portal/`

| Endpoint                  | Méthode | Auth | Description                            |
|---------------------------|---------|------|----------------------------------------|
| `submit/`                 | POST    | —    | Soumettre le formulaire (public)       |
| `verify/`                 | POST    | —    | Vérifier code double opt-in (public)   |
| `resend-verification/`    | POST    | —    | Renvoyer le code (public)              |
| `status/`                 | GET     | —    | Statut d'un client (public)            |

---

## Serializers

### FormSchemaSerializer

**Champs (lecture) :** `id`, `public_key`, `owner`, `name`, `title`, `description`, `logo`, `button_label`, `schema`, `double_opt_enable`, `enable`, `version`, `created_at`, `updated_at`

**Validation `schema` :**
- Doit contenir une clé `fields` (liste)
- Chaque champ doit avoir `name`, `label`, `type`
- Au moins 1 champ requis

---

### OwnerClientSerializer

**Champs (lecture) :** `id`, `mac_address`, `client_token`, `email`, `phone`, `payload`, `recognition_level`, `is_verified`, `tags`, `notes`, `created_at`, `updated_at`, `last_seen`

**Champs modifiables (PATCH) :** `tags`, `notes`

---

## Filtres

**Fichier :** `core_data/filters.py`

```python
class OwnerClientFilter(FilterSet):
    is_verified = BooleanFilter()
    search      = CharFilter(method='search_filter')
    date_from   = DateFilter(field_name='created_at', lookup_expr='gte')
    date_to     = DateFilter(field_name='created_at', lookup_expr='lte')
```

---

## Configuration requise

### Cache analytics

```python
# Les métriques analytics sont mises en cache 3600 s (1 heure)
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
    }
}
```

### TTLs

| Clé de cache                   | TTL     | Usage                             |
|--------------------------------|---------|-----------------------------------|
| `email_verification_{user.id}` | 600 s   | Code OTP inscription/reset/email  |
| `double_opt_{client.id}`       | 300 s   | Code double opt-in portail        |
| `email_verification_rate_limit_*` | 60 s | Rate limit renvoi OTP             |
| Analytics dashboard            | 3600 s  | Cache métriques                   |

---

## Management Commands

### populate_core_data

Peuple la DB avec des schémas variés et des leads réalistes.

```bash
python manage.py populate_core_data                  # 100 leads (défaut)
python manage.py populate_core_data --leads 500      # 500 leads
python manage.py populate_core_data --clear --leads 200  # Vider et recréer
```

**Prérequis :** `populate_accounts` doit avoir été exécuté avant.

**Ce que la commande crée :**
- 1 schéma de formulaire par propriétaire (variantes : Simple, Complet, Marketing, Restaurant, Hôtel)
- N leads distribués selon une distribution Pareto (80/20)
- Données réalistes : Faker fr_FR, villes béninoises, MAC aléatoires
- Champs `tags` et `notes` sur certains leads

---

## Bonnes pratiques

### Accès aux leads — toujours filtrer par owner

```python
# ✅ CORRECT — jamais de fuite cross-owner
queryset = OwnerClient.objects.filter(owner=request.user)

# ❌ INCORRECT — expose les leads d'autres propriétaires
queryset = OwnerClient.objects.all()
```

### Invalider le cache après modification de schéma

```python
from django.core.cache import cache

# Invalider après modification du schéma
cache.delete(f'schema_{owner.id}')
```

### Ne jamais modifier `version` manuellement

```python
# ✅ CORRECT — auto-incrémenté par save() si schema change
schema.schema = new_fields
schema.save()

# ❌ INCORRECT
schema.version = 5
schema.save()
```

---

## Structure fichiers

```
core_data/
├── models.py                          # FormSchema + OwnerClient
├── serializers.py                     # DRF serializers
├── views.py                           # FormSchema, Lead, Analytics, Portal
├── filters.py                         # Filtres leads
├── services/
│   ├── verification_services.py       # Flux portail captif
│   ├── portal_services.py             # URL de redirection
│   ├── dashboard_services.py          # Analytics
│   └── messages_services.py           # Envoi messages
├── tests.py                           # Tests unitaires
└── management/commands/
    └── populate_core_data.py
```

---

**Documentation mise à jour le 17/04/2026**
