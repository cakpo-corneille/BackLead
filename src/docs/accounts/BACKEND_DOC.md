# Accounts App - Documentation Backend

**Version :** 5.0
**Date :** Avril 2026

---

## Architecture

Gestion complète authentification JWT + vérification email OTP + onboarding progressif + changement d'email.

**Composants :**
- User personnalisé (email comme identifiant unique)
- OwnerProfile avec calcul automatique de complétion
- Authentification JWT + double opt-in email
- Services métier réutilisables
- Validation stricte des données
- Système de changement d'email sécurisé

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
- `form_schema` → FormSchema (OneToOne, auto-créé par signal dans core_data)

---

### OwnerProfile

```python
class OwnerProfile(models.Model):
    MAIN_GOAL_CHOICES = [
        ('collect_leads', 'Collecter des leads'),
        ('analytics',     'Analyser le trafic'),
        ('marketing',     'Marketing ciblé'),
    ]

    user              = OneToOneField(User, related_name='profile')
    business_name     = CharField(max_length=255)
    logo              = ImageField(upload_to='logos/profile', default='logos/profile/default.png')
    nom               = CharField(max_length=150, blank=True)
    prenom            = CharField(max_length=150, blank=True)
    phone_contact     = CharField(max_length=20, blank=True)
    whatsapp_contact  = CharField(max_length=30, blank=True)
    pays              = CharField(max_length=100, blank=True)
    ville             = CharField(max_length=100, blank=True)
    quartier          = CharField(max_length=100, blank=True)
    main_goal         = CharField(max_length=50, choices=MAIN_GOAL_CHOICES, blank=True)
    pass_onboarding   = BooleanField(default=False, editable=False)  # Auto-calculé
    is_complete       = BooleanField(default=False, editable=False)  # Auto-calculé
```

**Méthode `save()` — Calcul automatique :**

```python
# pass_onboarding = True si TOUS ces checks passent :
required_checks = [
    business_name personnalisé (≠ f'WIFI-ZONE {user.id}'),
    logo personnalisé (≠ 'logos/profile/default.png'),
    nom renseigné,
    phone_contact OU whatsapp_contact renseigné,
    pays + ville + quartier renseignés,
    main_goal défini,
]

# is_complete = True si :
pass_onboarding = True
AND prenom renseigné
AND phone_contact ET whatsapp_contact renseignés
```

**Signal post_save sur User :**
Crée automatiquement un `OwnerProfile` avec `business_name=f'WIFI-ZONE {user.id}'` et le logo par défaut.

---

## Services métier

**Fichier :** `accounts/services.py`

### generate_verification_code()

Génère un code OTP de 6 chiffres.

**Returns :** `str` (ex : `'482917'`)

---

### send_verification_code(user)

Génère un code 6 chiffres, le stocke dans le cache (TTL `OTP_TTL = 600 s` / 10 min), et envoie l'email.

**Cache key :** `email_verification_{user.id}`

**Returns :** `str` (le code généré, utile pour les tests)

---

### verify_code(user, code)

Vérifie le code et positionne `is_verify=True` si valide.

**Returns :** `(success: bool, error_message: str)`

**Erreurs possibles :**
- `"Code expiré ou invalide. Demandez un nouveau code."`
- `"Code incorrect. Veuillez réessayer."`

---

### resend_verification_code(user)

Renvoie un nouveau code avec rate limiting (1 code/60 s).

**Rate limit key :** `email_verification_rate_limit_{user.id}` (TTL 60 s)

**Returns :** `(success: bool, message: str)`

---

### check_profile_completion(user)

**Returns :**
```python
{
    'pass_onboarding':       bool,   # Champs minimaux OK
    'is_complete':           bool,   # Profil 100 % complet
    'missing_fields':        list,   # Champs manquants
    'completion_percentage': int,    # 0-100
    'has_business_name':     bool,
    'has_logo':              bool,
    'has_main_goal':         bool,
    'has_contact':           bool,
    'has_location':          bool,
}
```

---

### send_password_reset_code(email)

Génère un code OTP pour réinitialiser le mot de passe.

**Cache key :** `password_reset_{user.id}` (TTL `OTP_TTL`)

**Returns :** `(success: bool, user_or_message: User|str)`

---

### reset_password_with_code(user_id, code, new_password)

Réinitialise le mot de passe après vérification du code.

**Returns :** `(success: bool, error_message: str)`

---

### change_password(user, old_password, new_password)

Change le mot de passe d'un utilisateur authentifié.

**Returns :** `(success: bool, error_message: str)`

---

### send_change_email_code(user, new_email)

Génère et envoie un code de confirmation au **nouvel** email.

**Cache key :** `change_email_{user.id}` → stocke `{'new_email': str, 'code': str}` (TTL `OTP_TTL`)

**Returns :** `str` (le code généré)

---

## Validators

### validate_password_strength(value)

**Règles :**
- 8 à 15 caractères
- Au moins 1 majuscule
- Au moins 1 minuscule
- Au moins 1 chiffre

**Raises :** `ValidationError` si invalide

---

## Tâches Celery

### send_verification_code_task(user_pk)

Envoie le code OTP d'inscription de façon asynchrone.

**Config :**
- Max retries : 3
- Retry delay : 60 s
- Backoff : True

**Fallback dans la view :** Si Celery échoue → appel synchrone direct via `send_verification_code(user)`.

---

## ViewSets & Endpoints

### AuthViewSet

**Base :** `/api/v1/accounts/auth/`

| Endpoint           | Méthode | Auth   | Description                            |
|--------------------|---------|--------|----------------------------------------|
| `register/`        | POST    | Public | Inscription + envoi OTP                |
| `verify/`          | POST    | Public | Vérification code OTP → tokens JWT     |
| `resend_code/`     | POST    | Public | Renvoyer code (rate limit 60 s)        |
| `login/`           | POST    | Public | Connexion JWT                          |
| `forgot_password/` | POST    | Public | Demande reset mot de passe             |
| `reset_password/`  | POST    | Public | Reset mdp avec code OTP                |
| `logout/`          | POST    | Auth   | Déconnexion symbolique (JWT stateless) |

---

### ProfileViewSet

**Base :** `/api/v1/accounts/profile/`

| Endpoint           | Méthode    | Auth | Description                                  |
|--------------------|------------|------|----------------------------------------------|
| `me/`              | GET        | Auth | Récupérer profil complet + statut            |
| `me/`              | PATCH/PUT  | Auth | Mettre à jour profil (multipart pour logo)   |
| `status/`          | GET        | Auth | Statut de complétion uniquement              |
| `change_password/` | POST       | Auth | Changer mot de passe                         |
| `change_email/`    | POST       | Auth | Initier changement d'email (envoi code OTP)  |

**Parsers :** `MultiPartParser`, `FormParser`, `JSONParser`

---

## Serializers

### RegisterSerializer

**Champs :** `email`, `password` (write_only, validé via `validate_password_strength`)

**Méthode `create()` :** Normalise email + crée User en transaction atomique

---

### VerifyCodeSerializer

**Champs :** `user_id`, `code` (6 chiffres, chiffres uniquement)

---

### LoginSerializer

**Champs :** `email`, `password`

**Méthode `validate()` :** Authentifie via `authenticate()` + retourne erreur si email non vérifié

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

### ChangeEmailSerializer

**Champs :** `new_email` (validé : email unique dans la base)

---

### OwnerProfileSerializer

**Champs :** `user` (read-only), `business_name`, `logo`, `logo_url` (read-only), `nom`, `prenom`, `phone_contact`, `whatsapp_contact`, `pays`, `ville`, `quartier`, `main_goal`, `is_complete` (read-only)

**Validation logo :**
- Max 2 MB
- Formats autorisés : JPEG, PNG, WebP

**`logo_url` :** URL absolue construite via `request.build_absolute_uri()`

---

## Configuration requise

### JWT (SimpleJWT)

```python
SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME':  timedelta(hours=24),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=7),
    'ROTATE_REFRESH_TOKENS':  True,
    'BLACKLIST_AFTER_ROTATION': True,  # Invalide les anciens refresh tokens
}
```

### Cache (OTP)

```python
# Dev : LocMemCache (pas de Redis nécessaire)
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
    }
}

# Prod : Redis
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.redis.RedisCache',
        'LOCATION': 'redis://127.0.0.1:6379/1',
    }
}
```

**TTLs :**
- `OTP_TTL = 600` → 10 minutes (codes d'inscription, reset mdp, changement email)
- Rate limit resend : 60 secondes

### Email

```python
# Dev
EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'

# Prod (via Anymail)
EMAIL_BACKEND = 'anymail.backends.brevo.EmailBackend'
ANYMAIL = {'BREVO_API_KEY': os.getenv('EMAIL_API_KEY')}
DEFAULT_FROM_EMAIL = 'no-reply@votredomaine.com'
```

---

## Management Commands

### populate_accounts

Peuple la DB avec 12 utilisateurs de test réalistes (Bénin).

```bash
python manage.py populate_accounts            # Créer 12 propriétaires
python manage.py populate_accounts --clear    # Vider puis recréer
```

**Résultat :**
- Profils complets (pass_onboarding=True, is_complete=True)
- Logos générés avec PIL (initiales sur fond coloré)
- `is_verify=True`
- Mots de passe valides (format : MotDePasseP1)

---

## Bonnes pratiques

### Ne jamais créer manuellement un OwnerProfile

```python
# ✅ CORRECT — le signal post_save s'en charge
user = User.objects.create_user('email@test.com', 'Pass123')
profile = user.profile  # Déjà créé automatiquement

# ❌ INCORRECT
OwnerProfile.objects.create(user=user, ...)
```

### Ne jamais forcer pass_onboarding ou is_complete

```python
# ✅ CORRECT — calculés automatiquement par save()
profile.business_name = 'Mon Café'
profile.save()

# ❌ INCORRECT — sera recalculé et potentiellement annulé
profile.is_complete = True
profile.save()
```

### Toujours passer par les services

```python
# ✅ CORRECT
from accounts.services import send_verification_code
code = send_verification_code(user)

# ❌ INCORRECT — contourne la logique de cache
cache.set(f'email_verification_{user.id}', '123456', 600)
send_mail(...)
```

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
├── services.py            # Logique métier (OTP, profil, passwords)
├── signals.py             # Signal post_save → création OwnerProfile auto
├── tasks.py               # Tâches Celery (send_verification_code_task)
├── validators.py          # validate_password_strength
├── views.py               # AuthViewSet + ProfileViewSet
├── utils.py               # send_email_code_async_or_sync
├── tests.py               # Tests unitaires
└── management/commands/
    ├── populate_accounts.py
    ├── create_superuser.py
    └── send_test_email.py
```

---

**Documentation mise à jour le 17/04/2026**
