# WiFi Marketing Platform - Backend API

API REST Django pour un **widget de collecte de leads**, conçu pour s'intégrer et se superposer sur des **portails captifs WiFi existants** afin d'enrichir la collecte de données utilisateur.

---

## Vue d'ensemble

La plateforme agit comme une couche intermédiaire entre le portail captif et l'accès internet. Elle collecte des données clients (email, téléphone, informations personnalisées), propose un double opt-in par OTP, et fournit un tableau de bord analytics aux propriétaires d'établissements.

```
Client WiFi → Portail Captif → Widget de Collecte → [Double Opt-in OTP] → Accès Internet
```

---

## Stack technique

| Composant        | Technologie                              |
|------------------|------------------------------------------|
| Framework        | Django 5.x + Django REST Framework       |
| Authentification | JWT (SimpleJWT) + OTP par email          |
| Base de données  | PostgreSQL (prod) / SQLite (dev)         |
| Cache            | Redis (prod) / LocMemCache (dev)         |
| Emails           | Brevo/Anymail (prod) / Console (dev)     |
| Tâches async     | Celery + Redis                           |
| Déploiement      | Replit (dev) / VPS (prod)               |

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

```bash
cp src/config/dev.py.example src/config/dev.py   # Si disponible
# Sinon, dev.py est déjà configuré pour le développement local
```

### 4. Migrations

```bash
cd src
python manage.py migrate --settings=config.settings
```

### 5. Données de test

```bash
# Créer 12 propriétaires de test
python manage.py populate_accounts --settings=config.settings

# Créer les schémas et 100 leads de test
python manage.py populate_core_data --settings=config.settings

# Options avancées
python manage.py populate_core_data --leads 500 --settings=config.settings
python manage.py populate_core_data --clear --leads 200 --settings=config.settings
```

### 6. Lancer le serveur

```bash
cd src
python manage.py runserver 0.0.0.0:5000 --settings=config.settings
```

L'API est accessible à : `http://localhost:5000/api/v1/`

---

## Structure du projet

```
.
├── requirements.txt
├── README.md
└── src/
    ├── manage.py
    ├── config/
    │   ├── settings.py          # Point d'entrée settings
    │   ├── base.py              # Config commune
    │   ├── dev.py               # Config développement
    │   └── prod.py              # Config production
    ├── api/
    │   └── v1.py                # Routeur principal API v1
    ├── accounts/                # Auth + profils propriétaires
    │   ├── models.py            # User + OwnerProfile
    │   ├── views.py             # AuthViewSet + ProfileViewSet
    │   ├── services.py          # Logique OTP + profil + passwords
    │   ├── serializers.py
    │   ├── signals.py           # Création auto OwnerProfile
    │   ├── tasks.py             # Tâches Celery
    │   ├── validators.py
    │   └── management/commands/
    │       ├── populate_accounts.py
    │       ├── create_superuser.py
    │       └── send_test_email.py
    ├── core_data/               # Widget + Leads + Analytics
    │   ├── models.py            # FormSchema + OwnerClient
    │   ├── views.py             # Schema, Lead, Analytics, Portal
    │   ├── serializers.py
    │   ├── filters.py
    │   ├── services/
    │   │   ├── verification_services.py
    │   │   ├── portal_services.py
    │   │   ├── dashboard_services.py
    │   │   └── messages_services.py
    │   └── management/commands/
    │       └── populate_core_data.py
    └── docs/
        ├── accounts/
        │   ├── BACKEND_DOC.md   # Architecture + modèles + services
        │   └── FRONTEND_DOC.md  # Endpoints + exemples + flux
        └── core_data/
            ├── BACKEND_DOC.md   # Architecture + modèles + services
            ├── FRONTEND_DOC.md  # Endpoints dashboard owner
            └── WIDGET_DOC.md    # Intégration widget portail captif
```

---

## Endpoints API

**Base :** `/api/v1/`

| Module      | Base URL               | Description                              |
|-------------|------------------------|------------------------------------------|
| Auth        | `accounts/auth/`       | Inscription, login, OTP, reset mdp       |
| Profil      | `accounts/profile/`    | Profil propriétaire, onboarding          |
| Schéma      | `schema/`              | Configuration formulaire widget          |
| Leads       | `leads/`               | Gestion des clients captés               |
| Analytics   | `analytics/`           | Métriques tableau de bord                |
| Portail     | `portal/`              | Flux widget public (soumission, OTP)     |

Les trailing slashes sont optionnelles (OptionalSlashRouter).

---

## Comptes de test

Après `populate_accounts`, ces comptes sont disponibles :

| Email                             | Mot de passe | Établissement              |
|-----------------------------------|--------------|----------------------------|
| cafe.akpakpa@example.com          | CafePass123  | Café des Palmes (Cotonou)  |
| restaurant.marina@example.com     | RestauPass1  | Restaurant Marina (Cotonou)|
| hotel.benin@example.com           | HotelPass1   | Hôtel du Bénin (Cotonou)   |
| bar.fidjrosse@example.com         | BarPass123   | Bar Le Rendez-vous         |
| salon.coiffure@example.com        | SalonPass1   | Salon Beauté Divine        |
| boutique.mode@example.com         | BoutiqueP1   | Boutique Élégance          |
| pizzeria.porto@example.com        | PizzaPass1   | Pizzeria Porto-Novo        |
| gym.fitness@example.com           | GymPass123   | Fitness Club               |
| librairie.savoir@example.com      | LibraPass1   | Librairie du Savoir        |
| clinique.sante@example.com        | CliniqueP1   | Clinique Santé Plus        |
| hotel.parakou@example.com         | ParakouP1    | Hôtel Parakou Palace       |
| maquis.ouidah@example.com         | OuidahP12    | Maquis Bord de Mer (Ouidah)|

Tous les comptes ont `is_verify=True` et leurs profils sont complets (`pass_onboarding=True`).

---

## Configuration

### Variables d'environnement (production)

```env
SECRET_KEY=<clé-secrète-django>
DATABASE_URL=postgresql://user:pass@host:5432/dbname
REDIS_URL=redis://127.0.0.1:6379/1
EMAIL_API_KEY=<clé-brevo>
```

### Paramètres clés

| Paramètre          | Valeur            | Description                          |
|--------------------|-------------------|--------------------------------------|
| `OTP_TTL`          | 600 s (10 min)    | Durée de validité des codes OTP      |
| `DOUBLE_OPT_TTL`   | 300 s (5 min)     | Durée du code double opt-in portail  |
| `ACCESS_TOKEN_LIFETIME` | 24 heures   | Durée du token JWT access            |
| `REFRESH_TOKEN_LIFETIME`| 7 jours     | Durée du token JWT refresh           |
| Analytics cache    | 3600 s (1 heure)  | Cache des métriques dashboard        |

---

## Flux principaux

### Inscription propriétaire

```
POST /auth/register/ → Reçoit user_id
POST /auth/verify/   → OTP reçu par email (10 min) → tokens JWT
PATCH /profile/me/   → Complétion profil (onboarding)
```

### Intégration widget portail captif

```
GET  /schema/{public_key}/public/ → Récupérer schéma formulaire
POST /portal/submit/              → Soumettre formulaire
POST /portal/verify/              → Vérifier OTP double opt-in (si activé)
```

### Gestion leads (dashboard)

```
GET  /leads/              → Liste paginée avec filtres
GET  /leads/export/       → Export CSV
PATCH /leads/{id}/        → Modifier tags / notes
GET  /analytics/overview/ → Métriques agrégées
```

---

## Documentation

La documentation complète est dans `src/docs/` :

- **`accounts/BACKEND_DOC.md`** — Architecture, modèles, services, validators, Celery
- **`accounts/FRONTEND_DOC.md`** — Tous les endpoints auth/profil avec exemples
- **`core_data/BACKEND_DOC.md`** — Modèles FormSchema/OwnerClient, services, configuration
- **`core_data/FRONTEND_DOC.md`** — Endpoints dashboard (leads, analytics, schéma)
- **`core_data/WIDGET_DOC.md`** — Intégration widget dans un portail captif

---

## Développement sur Replit

L'application est configurée pour tourner sur Replit avec :
- `ALLOWED_HOSTS = ['*']` en dev
- Port `5000` (webview Replit)
- Commande de lancement : `cd src && python manage.py runserver 0.0.0.0:5000 --settings=config.settings`

---

**Dernière mise à jour : 17/04/2026**
