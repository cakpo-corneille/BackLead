
# Tracking App — Documentation Backend

**Version :** 2.0
**Date :** Avril 2026
**Public :** Développeurs Backend, DevOps, Maintenance

---

## Architecture

L'application `tracking` capture et expose les **sessions WiFi** des
clients connectés à un hotspot MikroTik. Elle fonctionne en deux temps :

1. **tracker.js** (intégré dans `status.html` du routeur) envoie un
   premier heartbeat au moment de la connexion du client — crée la session
   et identifie le plan tarifaire via `$(session-timeout)`.

2. **Celery** interroge ensuite directement l'API RouterOS de chaque
   routeur MikroTik toutes les 2 minutes pour maintenir les sessions à
   jour, indépendamment du navigateur du client.

> ⚠️ Le navigateur du client n'est plus la source de vérité pour l'état
> d'une session. C'est MikroTik lui-même qui fait autorité.

**Composants :**
- 3 modèles : `TicketPlan` + `ConnectionSession` + `MikroTikRouter`
- Endpoints publics rate-limités pour les heartbeats
- Endpoints owner authentifiés : CRUD plans, CRUD routeurs, historique, analytics
- 2 tâches Celery : synchro MikroTik (2 min) + fermeture zombies (10 min)
- Identification automatique du plan via `session-timeout` MikroTik
- Nouveau fichier `mikrotik_api.py` : couche d'accès à l'API RouterOS

---

## Modèles

### TicketPlan

Plan tarifaire déclaré par l'owner. Identification automatique via
`$(session-timeout)` MikroTik — **plus de rx-limit / tx-limit**.

```python
class TicketPlan(models.Model):
    owner            = ForeignKey(User, related_name='ticket_plans')
    name             = CharField(max_length=100)
    price_fcfa       = PositiveIntegerField()
    duration_minutes = PositiveIntegerField()   # ex: 60 pour 1h, 240 pour 4h
    is_active        = BooleanField(default=True)
    created_at       = DateTimeField(auto_now_add=True)
    updated_at       = DateTimeField(auto_now=True)
```

> Les anciens champs `download_limit_mb` et `upload_limit_mb` ont été
> supprimés. La correspondance se fait uniquement par durée.

---

### MikroTikRouter

Informations de connexion à un routeur MikroTik d'un owner.
Un owner peut avoir plusieurs routeurs (plusieurs points WiFi).

```python
class MikroTikRouter(models.Model):
    owner               = ForeignKey(User, related_name='mikrotik_routers')
    name                = CharField(max_length=100)   # ex: "Boutique principale"
    host                = CharField(max_length=255)   # IP ou domaine
    port                = PositiveIntegerField(default=8728)
    username            = CharField(max_length=100)
    _password_encrypted = BinaryField()               # chiffré Fernet / SECRET_KEY
    is_active           = BooleanField(default=True)
    last_synced_at      = DateTimeField(null=True, blank=True)
    last_error          = TextField(blank=True, default='')
    created_at          = DateTimeField(auto_now_add=True)
    updated_at          = DateTimeField(auto_now=True)
```

**Méthodes :**
- `set_password(raw)` — chiffre et stocke le mot de passe.
- `get_password()` — déchiffre et retourne le mot de passe en clair.

> Le mot de passe est chiffré via `cryptography.fernet` en utilisant le
> `SECRET_KEY` Django comme clé de dérivation. Ne jamais lire
> `_password_encrypted` directement.

---

### ConnectionSession

Une session = un ticket WiFi = une connexion d'un client.
Créée au 1er heartbeat de `tracker.js`, mise à jour ensuite par Celery.

```python
class ConnectionSession(models.Model):
    # Relations
    owner       = ForeignKey(User, related_name='tracking_sessions')
    client      = ForeignKey(OwnerClient, related_name='sessions')
    ticket_plan = ForeignKey(TicketPlan, null=True, blank=True, on_delete=SET_NULL)
    router      = ForeignKey(MikroTikRouter, null=True, blank=True, on_delete=SET_NULL)

    # Identifiants réseau
    mac_address         = CharField(max_length=17, db_index=True)
    ip_address          = GenericIPAddressField(null=True, blank=True)
    ticket_id           = CharField(max_length=128, null=True, blank=True)
    mikrotik_session_id = CharField(max_length=128, null=True, blank=True)

    session_key = UUIDField(default=uuid.uuid4, unique=True, db_index=True)

    # Timing
    started_at     = DateTimeField(auto_now_add=True)
    ended_at       = DateTimeField(null=True, blank=True)
    last_heartbeat = DateTimeField(auto_now=True)

    # Durée totale du ticket — clé d'identification du plan
    session_timeout_seconds = PositiveIntegerField(default=0)

    # Consommation (mise à jour à chaque synchro Celery)
    uptime_seconds   = PositiveIntegerField(default=0)
    bytes_downloaded = BigIntegerField(default=0)
    bytes_uploaded   = BigIntegerField(default=0)

    is_active     = BooleanField(default=True, db_index=True)
    user_agent    = CharField(max_length=512, blank=True, default='')
    last_raw_data = JSONField(default=dict, blank=True)
```

**Propriétés calculées :**
- `duration_seconds` → utilise `ended_at` si défini, sinon `uptime_seconds`.
- `duration_human` → `"1h 23m 45s"`.
- `total_mb`, `download_mb`, `upload_mb`.

---

## Helpers de parsing MikroTik

**Fichier :** `tracking/models.py`

### parse_mikrotik_uptime(s)

Convertit `'1d2h34m56s'` en secondes. Les unités nulles sont omises
par MikroTik (`'5m12s'`, `'2h3s'` sont valides). Utilisé pour parser
`$(uptime)` et `$(session-timeout)`.

---

## Couche API MikroTik

**Fichier :** `tracking/mikrotik_api.py`

### router_connection(router)

Gestionnaire de contexte. Se connecte à l'API RouterOS via `librouteros`
sur le port configuré (8728 par défaut). Timeout de 10 secondes.
Ferme proprement la connexion à la sortie, même en cas d'erreur.

```python
with router_connection(router) as api:
    clients = list(api('/ip/hotspot/active/print'))
```

**Raises :**
- `ConnectionError` — routeur injoignable.
- `PermissionError` — identifiants refusés.

---

### test_router_connection(router)

Teste la connexion et retourne un résultat structuré.
Utilisé lors de la sauvegarde depuis le dashboard owner.

```python
# Succès
{'ok': True, 'clients_count': 5}

# Échec
{'ok': False, 'error': "Impossible de joindre 192.168.1.1:8728 — ..."}
```

---

### get_active_clients(api)

Récupère et normalise la liste des clients hotspot actifs depuis MikroTik.
Retourne une liste de dicts avec les clés normalisées :

```python
{
    'mac_address':             'AA:BB:CC:DD:EE:FF',
    'username':                'ABC123',
    'ip_address':              '192.168.1.10',
    'uptime_seconds':          5025,
    'session_timeout_seconds': 14400,   # durée totale du ticket
    'bytes_downloaded':        15234567,
    'bytes_uploaded':          8765432,
    'session_id':              '...',
}
```

---

### sync_router(router)

Synchronise les sessions en base avec l'état réel du routeur.

**Logique :**
1. Récupère la liste des clients actifs via `get_active_clients()`.
2. Pour chaque client dans MikroTik → met à jour sa session en base
   (uptime, bytes, ip). Si pas de session en base → crée-en une.
3. Pour chaque session active en base absente de la liste MikroTik →
   le client est déconnecté → ferme la session avec `ended_at = now`.
4. Met à jour `last_synced_at` et efface `last_error` sur le routeur.

**Returns :**
```python
{'updated': 12, 'created': 1, 'closed': 2}
```

> Un routeur injoignable log l'erreur dans `router.last_error` et
> ne plante pas les autres routeurs de la tâche Celery.

---

## Services métier

**Fichier :** `tracking/services.py`

### handle_heartbeat(payload, user_agent='')

Point d'entrée du 1er heartbeat tracker.js. Crée la session et identifie
le plan tarifaire. Après ce premier appel, c'est Celery qui prend le relais.

**Logique :**
1. Si `session_key` fourni → met à jour la session existante.
2. Sinon → résout l'owner via `public_key`, retrouve le client via MAC.
3. Crée la session avec `session_timeout_seconds` capturé depuis
   `$(session-timeout)`.
4. Appelle `match_ticket_plan()` pour identifier le plan.
5. Retourne `(session, created)`.

**Raises :** `ValueError` si `public_key` ou `mac_address` invalides.

---

### match_ticket_plan(owner, session_timeout_seconds)

Identifie le `TicketPlan` dont la durée correspond au `session-timeout`.
Prend le plan dont `duration_minutes * 60` est le plus proche de
`session_timeout_seconds`.

```python
# Exemple : session_timeout = 14400s → plan 240 min → "Pass 4h — 200F"
plan = match_ticket_plan(owner=owner, session_timeout_seconds=14400)
```

**Returns :** `TicketPlan | None`

---

### close_session(session_key)

Ferme proprement une session (`ended_at`, `is_active=False`). Idempotent.

---

### close_stale_sessions(threshold_minutes=10)

Filet de sécurité : ferme les sessions sans heartbeat depuis N minutes.
Utilisé si un routeur est hors ligne et que la synchro Celery échoue.

---

## Tâches Celery

**Fichier :** `tracking/tasks.py`

### tracking.sync_all_mikrotik_routers

Interroge tous les routeurs `is_active=True` et synchronise les sessions.
Ne lève jamais d'exception globale — un routeur défaillant n'arrête pas
les autres.

**Schedule :** toutes les **2 minutes**.

---

### tracking.close_stale_sessions

Filet de sécurité : ferme les sessions sans heartbeat depuis 10 minutes.

**Schedule :** toutes les **10 minutes**.

---

```python
# config/base.py
CELERY_BEAT_SCHEDULE = {
    'sync-mikrotik-routers': {
        'task': 'tracking.sync_all_mikrotik_routers',
        'schedule': 120,    # secondes
    },
    'close-stale-sessions': {
        'task': 'tracking.close_stale_sessions',
        'schedule': 600,    # secondes
    },
}
```

---

## ViewSets & Endpoints

### TrackingViewSet (public)

**Base :** `/api/v1/tracking/`
**Permissions :** `AllowAny`
**Rate limit :** 30 requêtes / 60 s par IP (sur `heartbeat`)

| Endpoint     | Méthode | Description                                   |
|--------------|---------|-----------------------------------------------|
| `heartbeat/` | POST    | Reçoit le 1er heartbeat depuis tracker.js     |
| `end/`       | POST    | Ferme une session (sendBeacon depuis logout)  |

> ⚠️ `heartbeat` ne renvoie **jamais 500** — exception interne → log
> silencieux + `200 {"ok": false}`.

---

### TicketPlanViewSet (owner)

**Base :** `/api/v1/ticket-plans/`
**Permissions :** `IsAuthenticated` (CRUD complet)

| Endpoint | Méthode                        | Description                    |
|----------|--------------------------------|--------------------------------|
| `/`      | GET / POST                     | Liste / créer un plan          |
| `{id}/`  | GET / PUT / PATCH / DELETE     | Détail / éditer / supprimer    |

---

### MikroTikRouterViewSet (owner)

**Base :** `/api/v1/routers/`
**Permissions :** `IsAuthenticated` (CRUD complet + actions)

| Endpoint                     | Méthode | Description                                      |
|------------------------------|---------|--------------------------------------------------|
| `/`                          | GET / POST | Liste / ajouter un routeur                    |
| `{id}/`                      | GET / PUT / PATCH / DELETE | Détail / modifier / supprimer   |
| `{id}/test-connection/`      | POST    | Teste la connexion et retourne le résultat       |
| `{id}/sync-now/`             | POST    | Force une synchronisation immédiate              |

**Réponse `test-connection/` :**
```json
// Succès
{"ok": true, "clients_count": 5}

// Échec (502)
{"ok": false, "error": "Impossible de joindre 192.168.1.1:8728"}
```

**Réponse `sync-now/` :**
```json
{"ok": true, "updated": 5, "created": 0, "closed": 1}
```

> Le mot de passe n'est **jamais retourné** en lecture (write-only).

---

### ConnectionSessionViewSet (owner, lecture seule)

**Base :** `/api/v1/sessions/`
**Permissions :** `IsAuthenticated`

| Endpoint | Méthode | Description              |
|----------|---------|--------------------------|
| `/`      | GET     | Historique des sessions  |
| `{id}/`  | GET     | Détail d'une session     |

**Filtres query string :**
- `?is_active=true|false`
- `?client={id}`
- `?date_from=YYYY-MM-DD&date_to=YYYY-MM-DD`

---

### SessionAnalyticsViewSet (owner)

**Base :** `/api/v1/session-analytics/`
**Permissions :** `IsAuthenticated`

| Endpoint       | Méthode | Description                               |
|----------------|---------|-------------------------------------------|
| `overview/`    | GET     | KPIs globaux (sessions, MB, revenus)      |
| `by-day/`      | GET     | Sessions par jour (`?days=30`, max 90)    |
| `by-hour/`     | GET     | Répartition par heure (heures de pointe)  |
| `top-clients/` | GET     | Top 10 clients                            |

---

## Serializers

### HeartbeatSerializer

| Champ            | Type       | Source MikroTik              |
|------------------|------------|------------------------------|
| `public_key`     | UUID       | attribut `data-public-key`   |
| `mac_address`    | str        | `data-mac` → `$(mac)`        |
| `ip_address`     | IP (opt)   | `data-ip` → `$(ip)`          |
| `uptime`         | str (opt)  | `data-uptime` → `$(uptime)`  |
| `session_timeout`| str (opt)  | `data-session-timeout` → `$(session-timeout)` |
| `bytes_in`       | str (opt)  | `data-bytes-in` → `$(bytes-in)` |
| `bytes_out`      | str (opt)  | `data-bytes-out` → `$(bytes-out)` |
| `username`       | str (opt)  | `data-username` → `$(username)` |
| `session_id`     | str (opt)  | `data-session-id` → `$(session-id)` |
| `session_key`    | UUID (opt) | retourné par le serveur      |

> Les champs `download_limit` / `upload_limit` ont été supprimés.

---

### MikroTikRouterSerializer

| Champ           | Lecture | Écriture | Notes                         |
|-----------------|---------|----------|-------------------------------|
| `id`            | ✅      | ❌       | auto                          |
| `name`          | ✅      | ✅       |                               |
| `host`          | ✅      | ✅       | IP ou domaine                 |
| `port`          | ✅      | ✅       | défaut 8728                   |
| `username`      | ✅      | ✅       |                               |
| `password`      | ❌      | ✅       | write-only, jamais retourné   |
| `is_active`     | ✅      | ✅       |                               |
| `last_synced_at`| ✅      | ❌       | mis à jour par Celery         |
| `last_error`    | ✅      | ❌       | vide si tout va bien          |
| `is_healthy`    | ✅      | ❌       | calculé : synced + no error   |

---

### TicketPlanSerializer

Champs : `id`, `name`, `price_fcfa`, `duration_minutes`, `is_active`,
`created_at`, `updated_at`.

> Les champs `download_limit_mb` / `upload_limit_mb` ont été supprimés.

---

### ConnectionSessionSerializer

Lecture seule. Inclut les champs calculés `duration_seconds`,
`duration_human`, `total_mb`, `download_mb`, `upload_mb` et les
champs dénormalisés `plan_name`, `plan_price_fcfa`,
`plan_duration_minutes`, `client_email`, `client_phone`, `router_name`.

---

## Dépendances à ajouter

```
librouteros     # client API RouterOS MikroTik
cryptography    # chiffrement Fernet pour les mots de passe routeurs
```

---

## Bonnes pratiques

### Toujours filtrer par owner sur les endpoints dashboard

```python
# ✅ CORRECT
qs = ConnectionSession.objects.filter(owner=request.user)

# ❌ INCORRECT — fuite cross-owner
qs = ConnectionSession.objects.all()
```

### Ne jamais renvoyer 500 sur les endpoints publics tracker

```python
try:
    handle_heartbeat(...)
except Exception:
    return Response({'ok': False}, status=200)
```

### Un routeur défaillant ne doit pas bloquer les autres

Dans `sync_all_mikrotik_routers`, chaque routeur est wrappé dans un
`try/except` individuel. L'erreur est loggée dans `router.last_error`
et la tâche continue avec les routeurs suivants.

---

## Admin

`tracking/admin.py` expose les trois modèles avec :
- `TicketPlan` : activer / désactiver en masse.
- `MikroTikRouter` : tester la connexion, voir le statut de synchro.
- `ConnectionSession` : forcer la fermeture, exporter en CSV.
- Filtres : `is_active`, `owner`, `started_at`.

---

## Structure fichiers

```
tracking/
├── models.py           # TicketPlan + MikroTikRouter + ConnectionSession
├── mikrotik_api.py     # Connexion RouterOS, sync sessions ↔ MikroTik
├── serializers.py      # Heartbeat, EndSession, TicketPlan, Router, Session
├── services.py         # handle_heartbeat, match_ticket_plan, close_session
├── tasks.py            # sync_all_mikrotik_routers + close_stale_sessions
├── views.py            # 5 ViewSets
├── admin.py            # Actions + export CSV
├── tests.py            # Tests unitaires et d'intégration
├── migrations/
│   ├── 0001_initial.py
│   ├── 0002_...py
│   └── 0003_mikrotikrouter_session_timeout.py
└── static/
    └── tracking/
        ├── tracker.js
        └── tracker.min.js
```

---

**Documentation mise à jour le 25/04/2026**

