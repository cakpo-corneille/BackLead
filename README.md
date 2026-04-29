# WiFiLeads — Backend API

API REST Django pour un **widget de collecte de leads et de suivi de sessions WiFi**, conçu pour s'intégrer sur des **portails captifs MikroTik existants** afin d'identifier les abonnés, constituer un registre conforme ARCEP, et fournir des analytics au gérant.

---

## Vue d'ensemble

La plateforme agit comme une couche intermédiaire entre le portail captif et l'accès internet. Elle collecte les données clients (nom, téléphone, email), propose un double opt-in par OTP SMS, suit les sessions WiFi en temps réel, et fournit un tableau de bord analytics complet aux propriétaires d'établissements.

```
Client WiFi → Portail Captif MikroTik → Widget WiFiLeads → [Double Opt-in OTP] → Accès Internet
                                              ↓
                                       Tracker WiFiLeads → Sessions en temps réel → Dashboard
```

---

## Stack technique

| Composant        | Technologie                              |
|------------------|------------------------------------------|
| Framework        | Django 5.x + Django REST Framework       |
| Authentification | JWT (SimpleJWT) + OTP par email/SMS      |
| Base de données  | PostgreSQL (prod) / SQLite (dev)         |
| Cache            | Redis (prod) / LocMemCache (dev)         |
| Emails           | Brevo/Anymail (prod) / Console (dev)     |
| SMS              | Brevo / FasterMessage / Hub2 / Console   |
| Tâches async     | Celery + Redis                           |
| IA               | Google Gemini (google-genai SDK)         |
| Stockage média   | S3-compatible / Railway Bucket (prod)    |
| Monitoring       | Sentry                                   |
| Déploiement      | Railway / VPS (prod), Replit (dev)       |

---

## Démarrage rapide

### 1. Prérequis

- Python 3.11+
- pip

### 2. Installation des dépendances

```bash
pip install -r requirements.txt
```

### 3. Configuration de l'environnement

Le fichier `src/config/dev.py` est pré-configuré pour le développement local (SQLite, cache mémoire, emails console, Celery synchrone). Aucune modification nécessaire pour démarrer.

Pour la production, copier `.env.example` et renseigner les variables :

```bash
cp .env.example .env
```

### 4. Migrations

```bash
cd src
python manage.py migrate --settings=config.settings
```

### 5. Données de test

Les commandes de peuplement doivent être lancées dans cet ordre :

```bash
# Étape 1 — Créer 12 propriétaires de test avec profils complets
python manage.py populate_accounts --settings=config.settings

# Étape 2 — Créer les schémas de formulaires et 100 leads par défaut
python manage.py populate_core_data --settings=config.settings

# Étape 3 — Créer les plans tarifaires et 150 sessions WiFi
python manage.py populate_tracking --settings=config.settings
```

Options avancées :

```bash
# Peuplement avec volumes personnalisés
python manage.py populate_core_data --leads 500 --settings=config.settings
python manage.py populate_tracking --sessions 300 --settings=config.settings

# Repartir de zéro (supprime et recrée)
python manage.py populate_core_data --clear --leads 200 --settings=config.settings
python manage.py populate_tracking --clear --sessions 200 --settings=config.settings
```

### 6. Lancer le serveur

```bash
cd src
python manage.py runserver 0.0.0.0:5000 --settings=config.settings
```

L'API est accessible à : `http://localhost:5000/api/v1/`
La documentation Swagger : `http://localhost:5000/api/docs/`

---

## Structure du projet

```
.
├── requirements.txt
├── README.md
├── .env.example
├── railway.toml
├── render.yaml
└── src/
    ├── manage.py
    ├── config/
    │   ├── settings.py          # Point d'entrée (dispatch dev/prod)
    │   ├── base.py              # Configuration commune
    │   ├── dev.py               # Overrides développement
    │   ├── prod.py              # Overrides production (secrets via env)
    │   ├── celery.py            # Configuration Celery
    │   ├── celery_utils.py      # Détection workers actifs
    │   ├── middleware.py        # HybridCORSMiddleware (CORS widget/portail)
    │   └── utils/
    │       ├── email_backend.py # Wrapper envoi email
    │       ├── sender.py        # Dispatch async/sync (email + SMS)
    │       └── sms_backend.py   # Factory SMS multi-provider
    ├── api/
    │   ├── v1.py                # Routeur principal OptionalSlashRouter
    │   ├── urls.py              # Montage API + Swagger + healthchecks
    │   └── healthcheck.py       # /health/, /ready/, /alive/
    ├── accounts/                # Auth + profils propriétaires
    │   ├── models.py            # User (AbstractBaseUser) + OwnerProfile
    │   ├── views.py             # AuthViewSet + ProfileViewSet
    │   ├── serializers.py
    │   ├── services.py          # OTP email, reset mdp, profil
    │   ├── signals.py           # Création auto OwnerProfile + nettoyage logos
    │   ├── tasks.py             # send_verification_code_task (Celery)
    │   ├── validators.py        # Règles mot de passe
    │   ├── utils.py             # send_email_code_async_or_sync
    │   └── management/commands/
    │       ├── populate_accounts.py   # 12 owners béninois de test
    │       ├── create_superuser.py
    │       ├── send_test_email.py
    │       └── upload_test_media.py
    ├── core_data/               # Widget + Leads + Analytics + Portail
    │   ├── models.py            # FormSchema + OwnerClient + ConflictAlert
    │   ├── views.py             # Lead, FormSchema, Analytics, Portal, Conflict
    │   ├── serializers.py       # Submission, Recognition, DoubleOptIn, etc.
    │   ├── filters.py           # LeadFilter (date, email, phone, verified)
    │   ├── decorators.py        # ratelimit_public_api (IP + cache.incr)
    │   ├── validators.py        # validate_schema_format + validate_payload_against_schema
    │   ├── signals.py           # FormSchema auto + invalidation cache analytics
    │   ├── tasks.py             # send_verification_code_task + send_whatsapp_alert_task
    │   ├── services/
    │   │   ├── portal/
    │   │   │   ├── portal_services.py       # provision, recognize, ingest
    │   │   │   ├── verification_services.py # detect_existing_client, handle_conflict
    │   │   │   └── messages_services.py     # send_verification_code (OTP SMS)
    │   │   └── dashboard/
    │   │       └── analytics.py             # analytics_summary + cache Redis
    │   ├── static/core_data/
    │   │   ├── widget.js                    # Widget portail captif (non minifié)
    │   │   └── widget.min.js                # Version production
    │   └── management/commands/
    │       ├── populate_core_data.py        # Leads + schémas de test
    │       └── check_prod_settings.py
    ├── tracking/                # Sessions WiFi MikroTik + Plans tarifaires
    │   ├── models.py            # TicketPlan + ConnectionSession + parsers MikroTik
    │   ├── views.py             # TrackingViewSet + TicketPlan + Sessions + Analytics
    │   ├── serializers.py       # Heartbeat, EndSession, TicketPlan, ConnectionSession
    │   ├── services.py          # handle_heartbeat, close_session, match_ticket_plan
    │   ├── tasks.py             # cleanup_stale_sessions (Celery Beat)
    │   ├── admin.py             # Actions bulk + export CSV
    │   ├── static/tracking/
    │   │   ├── tracker.js       # Script status.html / logout.html (non minifié)
    │   │   └── tracker.min.js   # Version production
    │   └── management/commands/
    │       └── populate_tracking.py         # Plans + sessions WiFi de test
    ├── assistant/               # Assistant IA Gemini
    │   ├── models.py            # ChatConversation + ChatMessage
    │   ├── views.py             # AssistantViewSet + ChatConversationViewSet
    │   ├── serializers.py
    │   ├── services.py          # chat() + generate_form_schema()
    │   └── gemini_client.py     # Wrapper google-genai (singleton lru_cache)
    ├── templates/
    │   └── emails/
    │       ├── base_email.html
    │       ├── auth/verification_code.html
    │       └── auth/change_email_code.html
    └── docs/
        ├── accounts/
        │   ├── BACKEND_DOC.md
        │   └── FRONTEND_DOC.md
        ├── core_data/
        │   ├── BACKEND_DOC.md
        │   ├── FRONTEND_DOC.md
        │   └── WIDGET_DOC.md
        ├── tracking/
        │   ├── BACKEND_DOC.md
        │   └── FRONTEND_DOC.md
        └── assistant/
            ├── BACKEND_DOC.md
            └── FRONTEND_DOC.md
```

---

## Endpoints API

**Base :** `/api/v1/`

| Module               | Base URL                   | Accès         | Description                                 |
|----------------------|----------------------------|---------------|---------------------------------------------|
| Auth                 | `accounts/auth/`           | Public        | Inscription, login, OTP, reset mdp          |
| Profil               | `accounts/profile/`        | Authentifié   | Profil propriétaire, onboarding             |
| Schéma               | `schema/`                  | Authentifié   | Configuration formulaire widget             |
| Leads                | `leads/`                   | Authentifié   | Gestion CRM des clients captés              |
| Alertes conflits     | `alerts/`                  | Authentifié   | Conflits MAC/email/phone détectés           |
| Analytics leads      | `analytics/`               | Authentifié   | Métriques leads et fidélité                 |
| Portail (widget)     | `portal/`                  | Public        | Flux widget : provision, submit, OTP        |
| Tracking (tracker)   | `tracking/`                | Public        | Heartbeats sessions MikroTik                |
| Plans tarifaires     | `ticket-plans/`            | Authentifié   | CRUD plans WiFi                             |
| Sessions WiFi        | `sessions/`                | Authentifié   | Historique sessions (lecture seule)         |
| Analytics sessions   | `session-analytics/`       | Authentifié   | KPIs sessions, par jour/heure, top clients  |
| Assistant IA         | `assistant/`               | Authentifié   | Chat Gemini + génération de formulaire      |
| Conversations IA     | `assistant/conversations/` | Authentifié   | Historique conversations                    |
| Healthchecks         | `/api/health/`, `/api/ready/`, `/api/alive/` | Public | Monitoring et probes K8s |
| Documentation        | `/api/docs/`               | Public        | Swagger UI                                  |

Les trailing slashes sont optionnelles (`OptionalSlashRouter`).

---

## Flux principaux

### Inscription propriétaire

```
POST /accounts/auth/register/  → Reçoit user_id
POST /accounts/auth/verify/    → OTP reçu par email (10 min) → tokens JWT
PATCH /accounts/profile/me/    → Complétion profil (onboarding)
```

### Intégration widget portail captif

```
GET  /portal/provision/?public_key={uuid}  → Schéma formulaire + infos owner
POST /portal/recognize/                    → Reconnaissance client existant (MAC / token)
POST /portal/submit/                       → Soumission lead + validation payload
POST /portal/confirm/                      → Vérification code OTP double opt-in
POST /portal/resend/                       → Renvoi code OTP
```

### Tracking sessions WiFi (tracker.js)

```
POST /tracking/heartbeat/  → Heartbeat depuis status.html MikroTik (toutes les ~60s)
POST /tracking/end/        → Fermeture session depuis logout.html (sendBeacon)
```

### Dashboard owner — leads

```
GET   /leads/              → Liste paginée avec filtres (date, email, phone, verified)
GET   /leads/export/       → Export CSV
PATCH /leads/{id}/         → Modifier tags / notes
GET   /analytics/summary/  → Métriques agrégées (cache Redis 1h)
```

### Dashboard owner — sessions WiFi

```
GET /ticket-plans/                    → Liste des plans tarifaires
POST /ticket-plans/                   → Créer un plan
GET /sessions/                        → Historique sessions
GET /session-analytics/overview/      → KPIs globaux (revenus, durée moyenne)
GET /session-analytics/by-day/        → Courbe par jour
GET /session-analytics/by-hour/       → Heures de pointe
GET /session-analytics/top-clients/   → Top 10 clients WiFi
```

### Assistant IA

```
POST /assistant/chat/           → Chat conversationnel (Gemini)
POST /assistant/generate-form/  → Génération de schéma formulaire par prompt
GET  /assistant/conversations/  → Historique des conversations
```

---

## Comptes de test

Après `populate_accounts`, ces comptes sont disponibles (tous `is_verify=True`, profils complets) :

| Email                           | Mot de passe  | Établissement               | Ville    |
|---------------------------------|---------------|-----------------------------|----------|
| cafe.akpakpa@example.com        | CafePass123   | Café des Palmes             | Cotonou  |
| restaurant.marina@example.com   | RestauPass1   | Restaurant Marina           | Cotonou  |
| hotel.benin@example.com         | HotelPass1    | Hôtel du Bénin              | Cotonou  |
| bar.fidjrosse@example.com       | BarPass123    | Bar Le Rendez-vous          | Cotonou  |
| salon.coiffure@example.com      | SalonPass1    | Salon Beauté Divine         | Cotonou  |
| boutique.mode@example.com       | BoutiqueP1    | Boutique Élégance           | Cotonou  |
| pizzeria.porto@example.com      | PizzaPass1    | Pizzeria Porto-Novo         | Porto-Novo|
| gym.fitness@example.com         | GymPass123    | Fitness Club                | Cotonou  |
| librairie.savoir@example.com    | LibraPass1    | Librairie du Savoir         | Abomey-Calavi |
| clinique.sante@example.com      | CliniqueP1    | Clinique Santé Plus         | Cotonou  |
| hotel.parakou@example.com       | ParakouP1     | Hôtel Parakou Palace        | Parakou  |
| maquis.ouidah@example.com       | OuidahP12     | Maquis Bord de Mer          | Ouidah   |

---

## Configuration

### Variables d'environnement (production)

```env
# Sécurité
SECRET_KEY=<clé-secrète-django>
ENVIRONMENT=prod
ALLOWED_HOSTS=app.wifileads.io,www.wifileads.io

# Base de données
DATABASE_URL=postgresql://user:pass@host:5432/wifileads

# Cache & Celery
REDIS_URL=redis://127.0.0.1:6379/1
CELERY_BROKER_URL=redis://127.0.0.1:6379/0
CELERY_RESULT_BACKEND=redis://127.0.0.1:6379/0

# Email
EMAIL_PROVIDER=brevo                 # brevo | sendgrid | mailgun | smtp | console
EMAIL_API_KEY=<clé-api-email>
DEFAULT_FROM_EMAIL=WiFiLeads <no-reply@wifileads.io>

# SMS
SMS_PROVIDER=fastermessage           # fastermessage | hub2 | brevo | console
FASTERMESSAGE_API_KEY=<clé>
FASTERMESSAGE_SENDER_ID=WiFiLeads
FASTERMESSAGE_API_URL=https://api.fastermessage.com/v1/send

# Stockage médias (Railway Bucket ou S3)
BUCKET=<nom-bucket>
ACCESS_KEY_ID=<clé>
SECRET_ACCESS_KEY=<secret>
REGION=<region>
ENDPOINT=<endpoint-s3>

# IA
GEMINI_API_KEY=<clé-google-ai-studio>

# Monitoring
SENTRY_DSN=<dsn-sentry>

# CORS
CORS_ALLOWED_ORIGINS=https://app.wifileads.io,https://www.wifileads.io

# Logique métier
EMAIL_CHECK_DELIVERABILITY=true
SECURE_SSL_REDIRECT=true
```

### Paramètres clés

| Paramètre               | Valeur défaut   | Description                               |
|-------------------------|-----------------|-------------------------------------------|
| `OTP_TTL`               | 600 s (10 min)  | Durée de validité des codes OTP email     |
| `DOUBLE_OPT_TTL`        | 300 s (5 min)   | Durée du code double opt-in SMS portail   |
| `ACCESS_TOKEN_LIFETIME` | 24 heures        | Durée du token JWT access                 |
| `REFRESH_TOKEN_LIFETIME`| 7 jours          | Durée du token JWT refresh                |
| Analytics cache         | 3600 s (1 heure) | Cache Redis métriques leads dashboard     |
| Cleanup sessions        | toutes 5 min     | Fermeture sessions sans heartbeat > 10 min|

---

## Architecture CORS

L'app utilise une stratégie CORS hybride via `HybridCORSMiddleware` :

- **Endpoints portail** (`/api/v1/portal/*`) : CORS ouvert avec réflexion d'origine — nécessaire car le widget s'exécute depuis n'importe quel domaine de portail captif.
- **Endpoints tracker** (`/api/v1/tracking/*`) : même logique, le tracker peut être servi depuis le routeur.
- **Endpoints dashboard** : CORS strictement limité à `CORS_ALLOWED_ORIGINS`.

---

## SMS — Providers configurés

| Provider       | Région cible         | Config                                           |
|----------------|----------------------|--------------------------------------------------|
| FasterMessage  | Bénin / Togo         | `FASTERMESSAGE_API_KEY` + `FASTERMESSAGE_SENDER_ID` |
| Hub2           | Bénin / Togo / Afrique| `HUB2_TOKEN` + `HUB2_SENDER_ID`                 |
| Brevo          | International        | `BREVO_SMS_API_KEY` + `BREVO_SMS_SENDER_ID`      |
| Console        | Développement        | Pas de config — affiche dans le terminal         |

---

## Développement sur Replit

L'application est configurée pour tourner sur Replit avec :
- `ALLOWED_HOSTS = ['*']` en dev
- Port `5000` (webview Replit)
- Celery en mode synchrone (`CELERY_TASK_ALWAYS_EAGER = True`)
- Cache mémoire locale (pas Redis)

```bash
cd src && python manage.py runserver 0.0.0.0:5000 --settings=config.settings
```

---

## Healthchecks

| Endpoint      | Usage                          | Vérifie                        |
|---------------|--------------------------------|--------------------------------|
| `/api/health/`| Monitoring externe             | DB + Redis + Celery (non-bloquant) |
| `/api/ready/` | Readiness probe Kubernetes     | DB + apps Django               |
| `/api/alive/` | Liveness probe Kubernetes      | Process vivant (toujours 200)  |

---

## Documentation technique

La documentation complète est dans `src/docs/` :

| Fichier                            | Public       | Contenu                                          |
|------------------------------------|--------------|--------------------------------------------------|
| `accounts/BACKEND_DOC.md`          | Backend      | Modèles User/OwnerProfile, services OTP, Celery  |
| `accounts/FRONTEND_DOC.md`         | Frontend     | Endpoints auth/profil avec exemples JSON         |
| `core_data/BACKEND_DOC.md`         | Backend      | FormSchema, OwnerClient, ingest, analytics       |
| `core_data/FRONTEND_DOC.md`        | Frontend     | Endpoints dashboard leads et analytics           |
| `core_data/WIDGET_DOC.md`          | Frontend     | Intégration widget dans un portail MikroTik      |
| `tracking/BACKEND_DOC.md`          | Backend      | TicketPlan, ConnectionSession, heartbeat, Celery |
| `tracking/FRONTEND_DOC.md`         | Frontend     | Endpoints sessions et analytics WiFi             |
| `assistant/BACKEND_DOC.md`         | Backend      | Gemini client, services chat et génération       |
| `assistant/FRONTEND_DOC.md`        | Frontend     | Endpoints chat et conversations                  |

---

**Dernière mise à jour : 22/04/2026**
