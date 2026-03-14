# WiFi Marketing Platform - Backend API

API REST Django pour un **widget de collecte de leads**, conçu pour s\'intégrer et se superposer sur des **portails captifs WiFi existants** afin d\'enrichir la collecte de données utilisateur.

---

## 📋 Table des matières

- [Vue d\'ensemble](#-vue-densemble)
- [Stack technique](#-stack-technique)
- [Prérequis](#-prérequis)
- [Installation](#-installation)
- [Configuration](#️-configuration)
- [Démarrage](#-démarrage)
- [Structure du projet](#-structure-du-projet)
- [Déploiement](#-déploiement)
- [Tests](#-tests)
- [Troubleshooting](#-troubleshooting)

---

## 🎯 Vue d\'ensemble

### Principe de fonctionnement

Ce projet n\'est pas un système de portail captif complet. Il fournit une **API pour un widget JavaScript (SDK)** qui s\'intègre de manière indépendante sur n\'importe quelle page de portail captif existante.

Le rôle du widget est d\'afficher un formulaire en **superposition (overlay)**, de gérer le processus de collecte et de vérification des données de l\'utilisateur (avec double opt-in), puis de **se retirer**. Une fois les données collectées avec succès, le widget disparaît et laisse le portail captif d\'origine gérer la connexion finale de l\'utilisateur à Internet.

**Notre système se concentre uniquement sur l\'enrichissement de la collecte de données avant l\'accès final à Internet.**

### Fonctionnalités

**Gestion utilisateurs (Accounts)**
- Inscription/connexion JWT avec double opt-in email
- Profils propriétaires avec onboarding progressif
- Reset password via OTP
- Upload logo (PNG/JPEG/WebP, max 2MB)

**Collecte de leads (Core Data)**
- Formulaires personnalisables (max 5 champs, types multiples)
- Validation stricte email (email-validator) et téléphone (phonenumbers)
- Reconnaissance client par MAC address ou token
- Double opt-in configurable (email/SMS)
- Anti-duplicate intelligent (MAC, email, phone)
- Recognition level pour tracking fidélité

**Analytics & Dashboard**
- KPIs temps réel (total, semaine, taux vérification, taux retour)
- Top 20 clients fidèles avec loyalty percentage
- Distribution horaire des leads (24h glissantes)
- Export leads paginé (20/page, max 100)

**Sécurité & Performance**
- Rotation clés publiques UUID
- Rate limiting endpoints publics
- Cache Redis pour OTP (TTL 120s)
- Celery pour envois asynchrones
- Normalisation données (E164, lowercase email)

---

## 🛠 Stack technique

| Composant | Technologie | Version |
|-----------|-------------|---------|
| **Framework** | Django | 5.0 |
| **API** | Django REST Framework | 3.14 |
| **Auth** | JWT (SimpleJWT) | 5.3 |
| **Database** | PostgreSQL / SQLite | 15+ / 3.x |
| **Cache** | Redis | 7.x |
| **Queue** | Celery | 5.3 |
| **WSGI** | Gunicorn | 21.2 |
| **Email** | Anymail (Brevo, SendGrid, etc.) | - |
| **SMS** | Brevo / FasterMessage / Hub2 | - |

**Apps Django :**
- `accounts` : User + OwnerProfile + authentification
- `core_data` : FormSchema + OwnerClient + analytics
- `api` : Routing centralisé + health checks

---

## 📦 Prérequis

**Développement :**
- Python 3.11+
- Redis 7.x
- pip / virtualenv

**Production :**
- PostgreSQL 15+
- Redis 7.x
- Un fournisseur d\'email ou un serveur SMTP
- Un fournisseur de SMS (optionnel)

**Optionnel :**
- Docker & Docker Compose
- Sentry (monitoring erreurs)

---

## 🚀 Installation

### 1. Cloner et environnement virtuel

```bash
git clone <repository-url>
cd <project-folder>
python -m venv .venv
source .venv/bin/activate  # Linux/macOS
# .venv\Scripts\activate   # Windows
```

### 2. Installer dépendances

```bash
pip install -r requirements.txt
```

### 3. Redis

**Docker (recommandé) :**
```bash
docker run -d -p 6379:6379 --name redis redis:7-alpine
```

---

## ⚙️ Configuration

### Variables d\'environnement

Le projet est entièrement configuré via des variables d\'environnement, suivant les principes de la "12-Factor App".

**Développement :** Les settings se trouvent dans `src/config/dev.py`. Aucun fichier `.env` n\'est requis, le système est préconfiguré pour utiliser SQLite et le backend `console` pour les emails et SMS.

**Production :** Créez un fichier `.env` à la racine du projet (ou configurez les variables directement sur votre plateforme d\'hébergement).

```dotenv
# .env

# -- CONFIGURATION DE BASE --
# Doit être une chaîne de caractères longue et aléatoire
SECRET_KEY=votre_secret_key_longue_et_aleatoire
# Mettre à False en production
DEBUG=False
# Vos domaines de production (ex: mon-projet.on-railway.app,api.mon-domaine.com)
ALLOWED_HOSTS=...

# -- BASE DE DONNÉES (PostgreSQL) --
DATABASE_URL=postgres://user:password@host:port/dbname

# -- REDIS --
# Utilisé par Celery pour les tâches asynchrones (DB 0)
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/0
# Utilisé pour le cache de l'application (DB 1)
REDIS_URL=redis://localhost:6379/1

# -- CORS (Cross-Origin Resource Sharing) --
# Liste des domaines autorisés à appeler l'API du portail public (widget)
# Ex: https://portail-wifi.client-a.com,https://portail-wifi.client-b.com
CORS_ALLOWED_ORIGINS=...

# -- CONFIGURATION EMAIL (Exemple avec Brevo/Sendinblue) --
# Options: brevo, sendgrid, mailgun, smtp, console
EMAIL_PROVIDER=brevo
# La clé API de votre fournisseur
EMAIL_API_KEY=xkeysib-aabbccddeeff...
# L'email d'envoi par défaut
DEFAULT_FROM_EMAIL="Votre Marque <no-reply@votre-domaine.com>"

# -- CONFIGURATION SMS (Exemple avec FasterMessage) --
# Options: fastermessage, hub2, brevo, console
SMS_PROVIDER=fastermessage
# Variables spécifiques au fournisseur choisi
FASTERMESSAGE_API_KEY=votre_cle_api_fastermessage
FASTERMESSAGE_SENDER_ID=VotreMarque

# -- SENTRY (Optionnel, pour le suivi des erreurs) --
SENTRY_DSN=https://...@sentry.io/...

```

### Migrations & superuser

```bash
python src/manage.py migrate
python src/manage.py createsuperuser
```

---

## ▶️ Démarrage

### Terminal 1 - Django

```bash
python src/manage.py runserver
```

### Terminal 2 - Celery Worker

```bash
celery -A config.celery worker --loglevel=info
```

### Accès

- **API Base:** http://localhost:8000/api/v1/
- **Admin:** http://localhost:8000/admin/
- **Swagger:** http://localhost:8000/api/docs/
- **Health:** http://localhost:8000/api/health/

---

## 📁 Structure du projet

```
.
├── src/
│   ├── config/             # Fichiers de configuration centraux (settings, urls, etc.)
│   ├── accounts/           # Gestion utilisateurs, profils et authentification
│   ├── core_data/          # Coeur du métier : schémas, leads, analytics
│   ├── api/                # Routage de l'API v1 et health checks
│   ├── media/              # Fichiers uploadés par les utilisateurs (logos)
│   └── static/             # Fichiers statiques (widget.js)
│
├── staticfiles/            # Destination de `collectstatic` (utilisé en prod)
├── requirements.txt
├── manage.py
├── Procfile                # Définit les processus pour les plateformes PaaS (web, worker)
├── railway.toml            # Configuration de build et déploiement pour Railway
├── .env.example            # Exemple de fichier de configuration
└── README.md
```

---

## 🚢 Déploiement

La méthode recommandée est d\'utiliser une plateforme PaaS (Platform-as-a-Service) comme **Railway**, qui simplifie grandement le processus.

### Déploiement sur une Plateforme (Ex: Railway)

Ce projet est pré-configuré pour un déploiement "zéro effort" sur Railway.

1.  **`Procfile`**: Ce fichier déclare les processus qui font tourner votre application :
    - `web`: Lance le serveur Gunicorn pour répondre aux requêtes HTTP.
    - `worker`: Lance Celery pour exécuter les tâches asynchrones (envoi d'emails/SMS).

2.  **`railway.toml`**: Ce fichier orchestre le déploiement :
    - **Phase `[build]`**: Installe les dépendances et exécute `collectstatic`.
    - **Phase `[deploy]`**: Exécute les migrations de base de données (`migrate`) de manière sécurisée avant de lancer les services.
    - **Health Check**: Surveille l'endpoint `/api/health/` pour s'assurer que votre application est en bonne santé.

**Étapes :**
1.  Créez un projet sur Railway et liez-le à votre dépôt Git.
2.  Créez les services nécessaires : une base de données PostgreSQL et une instance Redis.
3.  Dans les "Variables" de votre projet Railway, ajoutez toutes les variables d'environnement listées dans la section **Configuration** ci-dessus (`SECRET_KEY`, `DATABASE_URL`, `CELERY_BROKER_URL`, etc.). Railway fournira automatiquement les URL pour la base de données et Redis.
4.  Lancez le déploiement. Railway lira automatiquement les fichiers `railway.toml` et `Procfile` et orchestrera tout le processus.

### Autres Méthodes de Déploiement

Les déploiements manuels via **Docker Compose** ou sur un **VPS** sont également possibles. Les fichiers `docker-compose.yml` et les instructions pour VPS dans l'ancienne version de ce README peuvent servir de base, mais il est crucial d'adapter la gestion des variables d'environnement pour correspondre à la nouvelle structure flexible (ex: `EMAIL_PROVIDER`, `FASTERMESSAGE_API_KEY`, etc.).

---

## 🧪 Tests

### Lancer tous les tests

```bash
python src/manage.py test
```

### Tests par app

```bash
python src/manage.py test src.accounts
python src/manage.py test src.core_data
```

### Tests avec coverage

```bash
pip install coverage
coverage run --source='src' src/manage.py test
coverage report
```

---

## 🔧 Troubleshooting

### CORS blocked

-   **Développement :** Dans `src/config/dev.py`, `CORS_ALLOW_ALL_ORIGINS` est à `True`, aucune action n'est requise.
-   **Production :** Assurez-vous que le domaine de votre widget est correctement listé dans la variable d'environnement `CORS_ALLOWED_ORIGINS`.

### Emails ou SMS non envoyés

-   Vérifiez que `EMAIL_PROVIDER` et `SMS_PROVIDER` sont correctement définis dans vos variables d'environnement.
-   Vérifiez que les clés API correspondantes (`EMAIL_API_KEY`, `FASTERMESSAGE_API_KEY`, etc.) sont correctes.
-   En production, vérifiez les logs de votre service `worker` (Celery) pour des messages d'erreur détaillés.

### Migrations conflictuelles

-   **En développement uniquement :** `rm src/db.sqlite3` puis `python src/manage.py migrate`.
-   **En production :** Si nécessaire, créez une migration de fusion avec `python src/manage.py makemigrations --merge`.

---

## 📚 Ressources

- **Documentation API :** `/api/docs/` (Swagger UI, disponible lorsque l'application tourne)
- **Postman Collection :** Sur demande

---

## 📝 Licence

Projet privé - Tous droits réservés

---

**Développé pour la captation de leads WiFi professionnelle**
