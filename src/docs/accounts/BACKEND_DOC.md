# Accounts App - Documentation Backend

**Version :** 4.0  
**Date :** Février 2026

---

## Architecture

Gestion complète authentification JWT + vérification email OTP + onboarding progressif.

**Composants :**
- User personnalisé (email comme identifiant unique)
- OwnerProfile avec calcul auto de complétion
- Authentification JWT + double opt-in email
- Services métier réutilisables
- Validation stricte données

---

## Modèles

### User

```python
class User(AbstractBaseUser, PermissionsMixin):
    email = EmailField(unique=True)
    is_active = BooleanField(default=True)
    is_staff = BooleanField(default=False)
    is_verify = BooleanField(default=False)  # Email vérifié via OTP
    date_joined = DateTimeField(default=timezone.now)
    
    USERNAME_FIELD = 'email'
```

**Manager :**
- `User.objects.create_user(email, password)`
- `User.objects.create_superuser(email, password)`

**Relations :**
- `profile` → OwnerProfile (OneToOne, auto-créé par signal)

---

### OwnerProfile

```python
class OwnerProfile(models.Model):
    MAIN_GOAL_CHOICES = [
        ('collect_leads', 'Collecter des leads'),
        ('analytics', 'Analyser le trafic'),
        ('marketing', 'Marketing ciblé'),
    ]
    
    user = OneToOneField(User, related_name='profile')
    business_name = CharField(max_length=255)
    logo = ImageField(upload_to='logos/', default='logos/default.png')
    nom = CharField(max_length=150, blank=True)
    prenom = CharField(max_length=150, blank=True)
    phone_contact = CharField(max_length=20, blank=True)
    whatsapp_contact = CharField(max_length=30, blank=True)
    pays = CharField(max_length=100, blank=True)
    ville = CharField(max_length=100, blank=True)
    quartier = CharField(max_length=100, blank=True)
    main_goal = CharField(max_length=50, choices=MAIN_GOAL_CHOICES, blank=True)
    pass_onboarding = BooleanField(default=False, editable=False)
    is_complete = BooleanField(default=False, editable=False)
```

**Méthode `save()` - Calcul automatique :**

```python
# pass_onboarding = True si :
required_checks = [
    business_name personnalisé (≠ f'WIFI-ZONE {user.id}'),
    logo personnalisé (≠ 'logos/default.png'),
    nom renseigné,
    phone_contact OU whatsapp_contact renseigné,
    pays + ville + quartier renseignés,
    main_goal défini
]

# is_complete = True si :
pass_onboading = True
+ prenom renseigné
+ phone_contact ET whatsapp_contact renseignés
```

**Signal post_save sur User :**
Crée automatiquement un OwnerProfile avec `business_name=f'WIFI-ZONE {user.id}'` et logo par défaut.

---

## Services métier

**Fichier :** `accounts/services.py`

### send_verification_code(user)

Génère code 6 chiffres, stocke Redis (TTL 3 min), envoie email.

**Returns :** `str` (code généré)

---

### verify_code(user, code)

Vérifie code + met `is_verify=True` si valide.

**Returns :** `(success: bool, error_message: str)`

**Erreurs possibles :**
- `"Code expiré ou invalide. Demandez un nouveau code."`
- `"Code incorrect. Veuillez réessayer."`

---

### resend_verification_code(user)

Renvoie nouveau code avec rate limiting (1/min).

**Returns :** `(success: bool, message: str)`

---

### check_profile_completion(user)

**Returns :**
```python
{
    'pass_onboading': bool,           # Champs minimaux OK
    'is_complete': bool,              # Profil 100% complet
    'missing_fields': list,
    'completion_percentage': int,     # 0-100
    'has_business_name': bool,
    'has_logo': bool,
    'has_main_goal': bool,
    'has_contact': bool,
    'has_location': bool
}
```

---

### send_password_reset_code(email)

Génère code OTP pour reset password.

**Returns :** `(success: bool, user_or_message: User|str)`

---

### reset_password_with_code(user_id, code, new_password)

Réinitialise mot de passe après vérification code.

**Returns :** `(success: bool, error_message: str)`

---

### change_password(user, old_password, new_password)

Change mot de passe utilisateur authentifié.

**Returns :** `(success: bool, error_message: str)`

---

## Validators

### validate_password_strength(value)

**Règles :**
- 8-15 caractères
- Au moins 1 majuscule
- Au moins 1 minuscule
- Au moins 1 chiffre

**Raises :** `ValidationError` si invalide

---

## ViewSets & Endpoints

### AuthViewSet

**Base :** `/api/v1/accounts/auth/`

| Endpoint | Méthode | Auth | Description |
|----------|---------|------|-------------|
| `register/` | POST | Public | Inscription + envoi OTP |
| `verify/` | POST | Public | Vérification code OTP |
| `resend_code/` | POST | Public | Renvoyer code (rate limit 60s) |
| `login/` | POST | Public | Connexion JWT |
| `forgot_password/` | POST | Public | Demande reset mdp |
| `reset_password/` | POST | Public | Reset mdp avec code |
| `logout/` | POST | Auth | Déconnexion symbolique |

---

### ProfileViewSet

**Base :** `/api/v1/accounts/profile/`

| Endpoint | Méthode | Auth | Description |
|----------|---------|------|-------------|
| `me/` | GET | Auth | Récupérer profil complet |
| `me/` | PATCH/PUT | Auth | Mettre à jour profil (multipart pour logo) |
| `status/` | GET | Auth | Statut complétion uniquement |
| `change_password/` | POST | Auth | Changer mot de passe |

**Parsers :** `MultiPartParser`, `FormParser`, `JSONParser`

---

## Serializers

### RegisterSerializer

**Champs :** `email`, `password` (write_only, validé)

**Méthode `create()` :** Normalise email + crée User en transaction atomique

---

### OwnerProfileSerializer

**Champs :** business_name, logo, nom, prenom, contacts, localisation, main_goal, is_complete (read-only)

**Validation logo :**
- Max 2MB
- Formats : PNG, JPEG, WebP

**SerializerMethodField :** `logo_url` (URL complète)

---

### VerifyCodeSerializer

**Champs :** `user_id`, `code` (6 chiffres)

---

### LoginSerializer

**Champs :** `email`, `password`

**Méthode `validate()` :** Authentifie via `authenticate()` + bloque si email non vérifié

---

### ForgotPasswordSerializer

**Champs :** `email`

---

### ResetPasswordSerializer

**Champs :** `user_id`, `code` (6 chiffres), `new_password` (validé)

---

### ChangePasswordSerializer

**Champs :** `old_password`, `new_password` (validé)

---

## Tâches asynchrones (Celery)

### send_verification_code_task(user_pk)

Envoie email OTP de façon asynchrone.

**Config :**
- Max retries : 3
- Retry delay : 60s
- Backoff : True

**Fallback :** Si Celery échoue, appel synchrone direct dans la view.

---

## Configuration requise

### Redis (Cache)

```python
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.redis.RedisCache',
        'LOCATION': 'redis://127.0.0.1:6379/1',
    }
}
```

**Utilisé pour :**
- Codes OTP (TTL 3 min)
- Rate limiting (TTL 60s)

---

### Email SMTP

```python
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = 'smtp.gmail.com'
EMAIL_PORT = 587
EMAIL_USE_TLS = True
EMAIL_HOST_USER = os.getenv('EMAIL_USER')
EMAIL_HOST_PASSWORD = os.getenv('EMAIL_PASSWORD')
DEFAULT_FROM_EMAIL = 'noreply@wifizone.com'
```

**Dev :** `EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'`

---

### JWT (SimpleJWT)

```python
from datetime import timedelta

SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(hours=1),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=7),
    'ROTATE_REFRESH_TOKENS': True,
}
```

---

## Management Commands

### populate_accounts

Peuple DB avec 10 utilisateurs de test.

**Usage :**
```bash
python manage.py populate_accounts
python manage.py populate_accounts --clear
```

**Résultat :**
- Profils complets avec logos générés (PIL)
- `is_verify=True`
- Mots de passe valides

---

## Bonnes pratiques

### Ne jamais créer manuellement un OwnerProfile

Le signal s'en charge.

```python
# ✅ CORRECT
user = User.objects.create_user('email@test.com', 'Pass123')
# profile créé automatiquement

# ❌ INCORRECT
OwnerProfile.objects.create(user=user, ...)
```

---

### Ne jamais forcer pass_onboading ou is_complete

Calculés automatiquement par `save()`.

```python
# ✅ CORRECT
profile.business_name = 'Mon Café'
profile.logo = uploaded_file
# ... remplir tous les champs
profile.save()
# → pass_onboading et is_complete calculés auto

# ❌ INCORRECT
profile.is_complete = True
profile.save()
# → Recalculé et possiblement remis à False
```

---

### Toujours utiliser les services

```python
# ✅ CORRECT
from accounts.services import send_verification_code
code = send_verification_code(user)

# ❌ INCORRECT
code = '123456'
cache.set(f'email_verification_{user.id}', code, 600)
send_mail(...)
```

---

### Gérer le fallback Celery

```python
try:
    send_verification_code_task.delay(user.id)
except Exception:
    send_verification_code(user)  # Fallback synchrone
```

---

## Structure fichiers

```
accounts/
├── models.py              # User + OwnerProfile
├── serializers.py         # DRF serializers
├── services.py            # Logique métier
├── signals.py             # Signal post_save
├── tasks.py               # Tâches Celery
├── validators.py          # Validation mot de passe
├── views.py               # ViewSets API
├── utils.py               # Helpers (send_code_async_or_sync)
├── tests.py               # Tests unitaires
└── management/commands/
    └── populate_accounts.py
```

---

**Documentation générée le 05/02/2026**
