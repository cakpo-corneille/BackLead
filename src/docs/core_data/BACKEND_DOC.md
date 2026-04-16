# WiFi Marketing Platform - Documentation Backend

**Version:** 2.0  
**Date:** Février 2026  
**Public:** Développeurs Backend, DevOps, Maintenance

---

## Table des matières

1. [Architecture technique](#architecture-technique)
2. [Modèles de données](#modèles-de-données)
3. [Services métier](#services-métier)
4. [Endpoints API](#endpoints-api)
5. [Validation](#validation)
6. [Double Opt-in](#double-opt-in)
7. [SMS Backends](#sms-backends)
8. [Signals](#signals)
9. [Configuration](#configuration)
10. [Déploiement](#déploiement)
11. [Monitoring](#monitoring)
12. [Scaling](#scaling)

---

## Architecture technique

### Stack
- **Framework:** Django 5.0
- **API:** Django REST Framework 3.14
- **Auth:** JWT (Simple JWT)
- **Cache:** Redis 7.x
- **Database:** PostgreSQL 15+ (production) / SQLite (dev)
- **Celery:** Workers asynchrones pour emails/SMS
- **Storage:** AWS S3 (fichiers statiques)

### Structure du projet
```
backend/
├── src/
│   ├── core_data/              # App principale
│   │   ├── models.py           # FormSchema, OwnerClient
│   │   ├── views.py            # ViewSets API
│   │   ├── serializers.py      # DRF Serializers
│   │   ├── validators.py       # Validation schema/payload
│   │   ├── signals.py          # Post-save hooks
│   │   ├── services/
│   │   │   ├── portal/
│   │   │   │   ├── portal_services.py
│   │   │   │   ├── messages_services.py
│   │   │   │   └── verification_services.py
│   │   │   └── dashboard/
│   │   │       └── analytics.py
│   │   └── tasks.py            # Celery tasks
│   ├── accounts/               # Gestion users
│   ├── config/                 # Settings Django & Global Utils
│   │   ├── utils/
│   │   │    ├── email_backend.py  # Global email utility
│   │   │    ├── sms_backend.py    # Abstraction SMS providers
│   │   │    └── sender.py         # Async or sync sender
│   │   └── settings.py         # Base/Dev/Prod config
└── static/
    └── core_data/
        └── widget.js           # Widget JavaScript
```

---

## Modèles de données

### FormSchema
**Fichier:** `core_data/models.py`

```python
class FormSchema(models.Model):
    owner = models.OneToOneField(User, on_delete=models.CASCADE, related_name='form_schema')
    name = models.CharField(max_length=120, default='default')
    schema = models.JSONField()
    public_key = models.UUIDField(default=uuid.uuid4, unique=True, db_index=True, editable=False)
    enable = models.BooleanField(default=True)
    version = models.PositiveIntegerField(default=0)
    
    double_opt_enable = models.BooleanField(default=False)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
```

**Relation:** `OneToOne` avec `User` → chaque owner a un seul schéma actif.

**Indexes:**
- `public_key` (unique, UUID4)
- `owner` (via ForeignKey)

**Méthodes importantes:**
```python
def save(self, *args, **kwargs):
    """Incrémente version uniquement en cas de changement structurel (champs/types)."""
    if self.pk:
        # Logique de fingerprinting technique (voir models.py)
        if self._has_structural_change():
            self.version += 1
    super().save(*args, **kwargs)

def rotate_public_key(self):
    """Génère nouvelle clé publique (sécurité)."""
    self.public_key = uuid.uuid4()
    super().save(update_fields=['public_key'])
```

**Format schema JSON:**
```json
{
  "fields": [
    {
      "name": "email",
      "label": "Email",
      "type": "email",
      "required": true,
      "placeholder": "votre@email.com"
    },
    {
      "name": "source",
      "type": "choice",
      "label": "Source",
      "choices": ["Facebook", "Instagram"],
      "required": false
    }
  ]
}
```

---

### OwnerClient
**Fichier:** `core_data/models.py`

```python
class OwnerClient(models.Model):
    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name='collected_data')
    mac_address = models.CharField(max_length=17, db_index=True)
    payload = models.JSONField()
    email = models.EmailField(max_length=254, null=True, blank=True)
    phone = models.CharField(max_length=40, null=True, blank=True)
    client_token = models.CharField(max_length=64, null=True, blank=True, unique=True)
    is_verified = models.BooleanField(default=False)
    recognition_level = models.PositiveIntegerField(default=0)
    
    last_seen = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        unique_together = [
            ('owner', 'mac_address'),
            ('owner', 'client_token')
        ]
        indexes = [
            models.Index(fields=['owner', 'email']),
            models.Index(fields=['owner', 'phone']),
            models.Index(fields=['owner', '-created_at']),
            models.Index(fields=['owner', '-last_seen'])
        ]
```

**Champs clés:**
- `mac_address`: Identifiant réseau (AA:BB:CC:DD:EE:FF)
- `client_token`: UUID généré côté serveur pour reconnaissance cross-device
- `email` / `phone`: Extraits du payload pour recherche rapide
- `recognition_level`: Compteur de visites (incrémenté à chaque retour)
- `is_verified`: Double opt-in validé

**Contraintes:**
- `(owner, mac_address)` unique → un seul lead par MAC par owner
- `(owner, client_token)` unique → évite duplicates tokens
- `client_token` unique globalement

---

## Services métier

### 1. Portal Services
**Fichier:** `core_data/services/portal/portal_services.py`

#### provision(public_key: str)
**Rôle:** Retourne schema + infos owner pour widget

**Logique:**
1. Vérifie `public_key` valide
2. Récupère `FormSchema` associé
3. Retourne schema + owner info (logo, business_name)

**Retour:**
```python
{
    'schema': {...},
    'owner': {
        'business_name': 'Mon Business',
        'logo': 'https://...'
    },
    'double_opt_enable': True,
    'enable': True
}
```

---

#### recognize(public_key: str, mac_address: str, client_token: str)
**Rôle:** Détecte si visiteur connu

**Logique:**
1. Recherche par `mac_address`
2. Si non trouvé → recherche par `client_token`
3. Si trouvé → retourne `recognized=True` + `is_verified`

**Retour:**
```python
{
    'recognized': True,
    'is_verified': True,
    'client_token': 'uuid...',
    'method': 'mac'  # ou 'token'
}
```

---

#### ingest(form_schema, mac_address, payload, client_token, verification_code)
**Rôle:** Ingestion lead avec gestion conflits

**Logique:**
1. Valide payload contre schema
2. Détecte conflits (MAC, email, phone)
3. Si nouveau → crée `OwnerClient` + génère token
4. Si duplicate → met à jour existant
5. Si conflit contact → vérifie code double opt-in
6. Incrémente `recognition_level` si retour

**Retour:**
```python
{
    'created': True,
    'duplicate': False,
    'conflict_field': None,
    'client_token': 'uuid...',
    'requires_verification': True  # Si double opt-in activé
}
```

**Fichier:** `core_data/services/portal/verification_services.py`

**Fonctions clés:**
- `detect_existing_client()`: Détection prioritaire MAC > token > email > phone
- `_handle_device_recognition()`: Mise à jour même device
- `_handle_contact_conflict()`: Gestion nouvelle device, même contact
- `_create_new_client()`: Création lead avec génération token

---

### 2. Messages Services
**Fichier:** `core_data/services/portal/messages_services.py`

#### send_verification_code(client, ttl_seconds=120)
**Rôle:** Envoie code 6 chiffres uniquement par SMS (Portail)

**Logique:**
1. Génère code 6 chiffres
2. Utilise uniquement le téléphone du client
3. Stocke code dans cache Redis : `double_opt_{client_token}`
4. Envoie via le backend SMS configuré globalement

**Retour:** `True` si succès, `False` si échec

---

#### verify_code(client, code)
**Rôle:** Valide code saisi

**Logique:**
1. Récupère code depuis cache
2. Compare avec code saisi
3. Si valide → supprime cache, retourne `(True, "")`
4. Si invalide → retourne `(False, "Code incorrect")`

---

#### resend_verification_code(client)
**Rôle:** Renvoie nouveau code (rate limited)

**Logique:**
1. Vérifie rate limit : `resend_rate_limit_{client_token}` → 60s
2. Appelle `send_code_async_or_sync(client)`
3. Set rate limit flag

**Retour:** `(True, "Nouveau code envoyé")` ou `(False, "Attendre 60s")`

---

### 3. Dashboard Analytics
**Fichier:** `core_data/services/dashboard/analytics.py`

#### analytics_summary(owner_id: int)
**Rôle:** KPIs et stats dashboard

**Requêtes SQL optimisées:**
```python
queryset = OwnerClient.objects.filter(owner_id=owner_id)

# Totaux
total = queryset.count()
week_ago = timezone.now() - timedelta(days=7)
this_week = queryset.filter(created_at__gte=week_ago).count()
verified = queryset.filter(is_verified=True).count()

# Taux de retour
returning = queryset.filter(recognition_level__gt=2).count()
return_rate = (returning / total * 100) if total > 0 else 0.0

# Top clients (loyalty threshold)
max_recognition = queryset.aggregate(Max('recognition_level'))['recognition_level__max']
threshold = max_recognition / 1.5 if max_recognition else 0
loyal = queryset.filter(recognition_level__gte=threshold).order_by('-recognition_level')[:20]

# Hourly distribution
day_ago = timezone.now() - timedelta(hours=24)
hourly = queryset.filter(created_at__gte=day_ago).annotate(
    hour=TruncHour('created_at')
).values('hour').annotate(count=Count('id')).order_by('hour')
```

**Retour:**
```python
{
    'total_leads': 1523,
    'leads_this_week': 87,
    'verified_leads': 1205,
    'return_rate': 34.2,
    'top_clients': [...],
    'leads_by_hour': [...]
}
```

---

## Endpoints API

### Portail Public (`/api/v1/portal/`)
**Permissions:** `AllowAny`  
**Rate limiting:** Actif

#### POST `/provision/`
**Query params:** `public_key`  
**Service:** `portal_services.provision()`

#### POST `/recognize/`
**Body:** `{public_key, mac_address, client_token?}`  
**Service:** `portal_services.recognize()`

#### POST `/submit/`
**Body:** `{public_key, mac_address, payload, client_token?, verification_code?}`  
**Service:** `portal_services.ingest()`

#### POST `/confirm/`
**Body:** `{client_token, code}`  
**Service:** `messages_services.verify_code()` → update `is_verified=True`

#### POST `/resend/`
**Body:** `{client_token}`  
**Service:** `messages_services.resend_verification_code()`

---

### Dashboard Owner (`/api/v1/schema/`)
**Permissions:** `IsAuthenticated` (JWT)

#### GET `/config/`
**ViewSet:** `FormSchemaViewSet.config()`  
**Retour:** FormSchema complet avec snippet

#### POST `/update_schema/`
**ViewSet:** `FormSchemaViewSet.update_schema()`  
**Validation:** `validators.validate_schema_format()`

#### POST `/rotate_key/`
**ViewSet:** `FormSchemaViewSet.rotate_key()`  
**Méthode:** `FormSchema.rotate_public_key()`

---

### Analytics (`/api/v1/analytics/`)
**Permissions:** `IsAuthenticated`

#### GET `/summary/`
**ViewSet:** `AnalyticsViewSet.summary()`  
**Service:** `analytics.analytics_summary()`

#### GET `/leads/`
**ViewSet:** `AnalyticsViewSet.leads()`  
**Pagination:** 20/page (max 100)  
**Tri:** `-last_seen`

---

## Validation

### Fichier: `core_data/validators.py`

#### validate_schema_format(schema: dict)
**Règles:**
- Maximum 5 champs
- Au moins 1 champ `email` OU `phone`
- Types autorisés : `text`, `email`, `phone`, `number`, `choice`, `boolean`
- Champ `email` doit avoir `name="email"`
- Type `choice` doit avoir array `choices`
- Pas de doublons de `name`

**Retour:** `(True, "ok")` ou `(False, "error message")`

---

#### validate_payload_against_schema(payload, schema, default_region="BJ")
**Validation stricte:**
- Email : `email-validator` avec `check_deliverability=False`
- Phone : `phonenumbers` → normalise en E164 (+22997000000)
- Number : conversion `float()`
- Choice : vérifie présence dans `choices`
- Boolean : type checking strict
- Required : vérifie présence si `required=True`

**Retour:** `(is_valid, error_msg, clean_payload)`

**Normalisation:**
```python
# Input
payload = {'email': 'John@EXAMPLE.COM', 'phone': '97000000'}

# Output clean_payload
{
    'email': 'john@example.com',  # Normalisé
    'phone': '+22997000000'       # E164 avec indicatif
}
```

---

## Double Opt-in

### Configuration
**FormSchema:**
- `double_opt_enable` : `True/False` (SMS Only)
- `enable` : `True/False` (Activer/Désactiver le formulaire)

### Flux
1. Client soumet formulaire
2. Si `double_opt_enable=True` → génère code 6 chiffres
3. Stocke dans Redis : `double_opt_{client_token}` → TTL 120s
4. Envoie code via canal préféré
5. Widget affiche input code
6. Client saisit code → `POST /confirm/`
7. Backend valide → `is_verified=True`

### Cache Keys
```python
# Code de vérification
cache_key = f"double_opt_{client.client_token}"
cache.set(cache_key, code, timeout=120)

# Rate limit resend
rate_limit_key = f"resend_rate_limit_{client.client_token}"
cache.set(rate_limit_key, True, timeout=60)
```

**IMPORTANT:** Clés séparées pour éviter collision (bug historique corrigé).

---

## SMS & Email Backends

### Fichier: `config/utils/sms_backend.py` & `email_backend.py`

### Architecture
Pattern **Strategy** avec classe abstraite `SMSBackend`.

```python
class SMSBackend(ABC):
    @abstractmethod
    def send(self, phone: str, message: str) -> bool:
        pass
```

### Implémentations

#### ConsoleSMSBackend (dev)
Affiche SMS dans console.

#### FasterMessageBackend (Bénin)
API FasterMessage pour MTN/Moov/Celtis.

**Configuration:**
```python
SMS_PROVIDER = 'fastermessage'
SMS_API_KEY = 'your_api_key'
SMS_SENDER_ID = 'YourBrand'
SMS_API_URL = 'https://api.fastermessage.com/v1/send'
```

**Payload:**
```json
{
  "apiKey": "...",
  "phone": "22997000000",  // Sans le +
  "message": "Votre code : 123456",
  "sender": "YourBrand"
}
```

#### Hub2SMSBackend (Bénin/Togo)
Alternative avec authentification Bearer.

**Configuration:**
```python
SMS_PROVIDER = 'hub2'
SMS_API_TOKEN = 'your_bearer_token'
SMS_SENDER_ID = 'YourBrand'
SMS_API_URL = 'https://api.hub2.com/sms/send'
```

### Factory
```python
def get_sms_backend():
    provider = getattr(settings, 'SMS_PROVIDER', 'console')
    
    if provider == 'fastermessage':
        return FasterMessageBackend()
    elif provider == 'hub2':
        return Hub2SMSBackend()
    else:
        return ConsoleSMSBackend()
```

### Ajout nouveau provider
1. Créer classe héritant `SMSBackend`
2. Implémenter `send(phone, message)`
3. Ajouter dans factory `get_sms_backend()`

---

## Signals

### Fichier: `core_data/signals.py`

#### create_default_form_schema
**Trigger:** `post_save` sur `User` (created=True)

**Rôle:** Crée automatiquement un FormSchema par défaut pour chaque nouvel owner.

```python
@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def create_default_form_schema(sender, instance, created, **kwargs):
    if not created:
        return
    
    FormSchema.objects.get_or_create(
        owner=instance,
        defaults={
            'schema': {
                'fields': [
                    {'name': 'nom', 'label': 'Nom', 'type': 'text', 'required': True},
                    {'name': 'email', 'label': 'Email', 'type': 'email', 'required': True}
                ]
            },
            'is_default': True
        }
    )
```

**Garantie:** Chaque owner a un schema dès sa création → évite 404 au premier login.


### Caching stratégique

#### Analytics cache
```python
# Cache analytics summary 5 minutes
cache_key = f"analytics_summary_{owner_id}"
data = cache.get(cache_key)

if not data:
    data = analytics_summary(owner_id)
    cache.set(cache_key, data, timeout=300)
```

#### FormSchema cache
```python
# Cache schema par public_key
cache_key = f"schema_{public_key}"
schema = cache.get(cache_key)

if not schema:
    schema = FormSchema.objects.get(public_key=public_key)
    cache.set(cache_key, schema, timeout=3600)
```

---
## Tests

### Lancer les tests
```bash
# Tous les tests
python manage.py test core_data

# Avec coverage
coverage run --source='.' manage.py test core_data
coverage report
coverage html  # Rapport HTML dans htmlcov/

# Tests spécifiques
python manage.py test core_data.tests.PortalAPITest
python manage.py test core_data.tests.AnalyticsSummaryTest -v 2
```

### Coverage cible
- **Modèles:** 100%
- **Services:** 95%+
- **Views:** 90%+
- **Validators:** 100%

### Commandes utiles

```bash
# Populate test data
python manage.py populate_core_data --leads 1000

# Shell Django
python manage.py shell_plus

# Migrations
python manage.py makemigrations
python manage.py migrate
python manage.py showmigrations

# Create superuser
python manage.py createsuperuser

# Check deployment
python manage.py check --deploy
```