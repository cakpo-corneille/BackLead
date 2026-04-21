# Tracking App — Documentation Backend

**Version :** 1.0
**Date :** Avril 2026
**Public :** Développeurs Backend, DevOps, Maintenance

---

## Architecture

L'application `tracking` capture et expose les **sessions WiFi** des
clients connectés à un hotspot MikroTik. Elle reçoit des heartbeats
publics depuis `tracker.js` (intégré dans `status.html` / `logout.html`
sur le routeur), associe chaque session à un `OwnerClient` et à un
`TicketPlan` quand c'est possible, et fournit une API analytics au
dashboard owner.

**Composants :**
- 2 modèles : `TicketPlan` (catalogue tarifaire) + `ConnectionSession` (sessions actives/historiques)
- Endpoints publics rate-limités pour les heartbeats
- Endpoints owner authentifiés : CRUD plans, historique, analytics
- Tâche Celery périodique de fermeture des sessions zombies
- Détection automatique du plan via les limites MikroTik (`rx-limit`/`tx-limit`)

---

## Modèles

### TicketPlan

Plan tarifaire déclaré par l'owner depuis son dashboard. Sert de
référence pour identifier automatiquement quel plan correspond à une
session MikroTik.

```python
class TicketPlan(models.Model):
    owner             = ForeignKey(User, related_name='ticket_plans')
    name              = CharField(max_length=100)
    price_fcfa        = PositiveIntegerField()
    duration_minutes  = PositiveIntegerField()
    download_limit_mb = PositiveIntegerField(null=True, blank=True)  # None = illimité
    upload_limit_mb   = PositiveIntegerField(null=True, blank=True)  # None = illimité
    is_active         = BooleanField(default=True)
    created_at        = DateTimeField(auto_now_add=True)
    updated_at        = DateTimeField(auto_now=True)
```

**Propriétés utilitaires :**
- `download_limit_bytes` / `upload_limit_bytes` : conversion MB → bytes (ou `None`).

---

### ConnectionSession

Une session = un ticket WiFi = une connexion d'un client. Même client,
tickets différents → sessions différentes. Mise à jour à chaque heartbeat
(refresh MikroTik de `status.html`).

```python
class ConnectionSession(models.Model):
    # Relations
    owner       = ForeignKey(User, related_name='tracking_sessions')
    client      = ForeignKey(OwnerClient, related_name='sessions')
    ticket_plan = ForeignKey(TicketPlan, null=True, blank=True, on_delete=SET_NULL)

    # Identifiants réseau (data-* MikroTik)
    mac_address          = CharField(max_length=17, db_index=True)
    ip_address           = GenericIPAddressField(null=True, blank=True)
    ticket_id            = CharField(max_length=128, null=True, blank=True, db_index=True)
    mikrotik_session_id  = CharField(max_length=128, null=True, blank=True)

    # Clé pour enchaîner les heartbeats
    session_key  = UUIDField(default=uuid.uuid4, unique=True, db_index=True)

    # Timing
    started_at     = DateTimeField(auto_now_add=True)
    ended_at       = DateTimeField(null=True, blank=True)
    last_heartbeat = DateTimeField(auto_now=True)

    # Consommation
    uptime_seconds       = PositiveIntegerField(default=0)
    bytes_downloaded     = BigIntegerField(default=0)
    bytes_uploaded       = BigIntegerField(default=0)
    download_limit_bytes = BigIntegerField(null=True, blank=True)
    upload_limit_bytes   = BigIntegerField(null=True, blank=True)

    is_active   = BooleanField(default=True, db_index=True)
    user_agent  = CharField(max_length=512, blank=True, default='')
    last_raw_data = JSONField(default=dict, blank=True)  # snapshot heartbeat brut
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
par MikroTik (`'5m12s'`, `'2h3s'` sont valides).

### parse_mikrotik_limit(s)

Convertit `'10M'` / `'512k'` / `'2G'` en bytes. Retourne `None` pour
`'---'`, `''` ou `'0'` (illimité).

---

## Services métier

**Fichier :** `tracking/services.py`

### handle_heartbeat(payload, user_agent='')

Point d'entrée des heartbeats. Crée ou met à jour la session.

**Logique :**
1. Identifie/crée le `OwnerClient` via `mac_address` (+ owner).
2. Cherche une `ConnectionSession` active correspondante (par `session_key`,
   sinon par `(owner, mac_address, is_active=True)`).
3. Crée la session si aucune trouvée et associe le `TicketPlan` détecté.
4. Met à jour `uptime_seconds`, `bytes_*`, `last_heartbeat`, `last_raw_data`.
5. Capture le `user_agent` au premier heartbeat.

**Returns :** `(session: ConnectionSession, created: bool)`

**Raises :** `ValueError` si `owner_id` ou `mac_address` invalides.

---

### close_session(session_key)

Ferme proprement une session (positionne `ended_at`, `is_active=False`).
Idempotent.

**Returns :** `bool` — True si la session existait et était active.

---

### detect_ticket_plan(owner, download_limit, upload_limit, uptime)

Détection automatique du plan correspondant aux limites MikroTik
(rapproche `rx-limit`/`tx-limit` de `download_limit_bytes`/`upload_limit_bytes`).
Si les limites sont illimitées, fallback sur `duration_minutes`.

**Returns :** `TicketPlan | None`

---

## Tâches Celery

### tracking.cleanup_stale_sessions

Ferme automatiquement les sessions dont le dernier heartbeat date de
plus de **15 minutes** (sessions zombies — client disparu sans logout).

**Schedule :** toutes les **5 minutes** (`CELERY_BEAT_SCHEDULE` dans
`config/base.py`).

```python
CELERY_BEAT_SCHEDULE = {
    'cleanup-stale-sessions': {
        'task': 'tracking.cleanup_stale_sessions',
        'schedule': 300.0,
    },
}
```

---

## ViewSets & Endpoints

### TrackingViewSet (public)

**Base :** `/api/v1/tracking/`
**Permissions :** `AllowAny`
**Rate limit :** 30 requêtes / 60 s par IP (sur `heartbeat`)

| Endpoint     | Méthode | Description                                 |
|--------------|---------|---------------------------------------------|
| `heartbeat/` | POST    | Reçoit un heartbeat depuis tracker.js       |
| `end/`       | POST    | Ferme une session (sendBeacon depuis logout)|

> ⚠️ **Politique d'erreur** : `heartbeat` ne renvoie **jamais 500** —
> en cas d'exception interne, on log et on retourne `200 {"ok": false}`
> pour ne pas casser le tracker côté client.

---

### TicketPlanViewSet (owner)

**Base :** `/api/v1/ticket-plans/`
**Permissions :** `IsAuthenticated` (CRUD complet)

| Endpoint    | Méthode               | Description                |
|-------------|-----------------------|----------------------------|
| `/`         | GET / POST            | Liste / créer un plan      |
| `{id}/`     | GET / PUT / PATCH / DELETE | Détail / éditer / supprimer |

`owner` est forcé via `perform_create` (jamais lisible/modifiable côté client).

---

### ConnectionSessionViewSet (owner, lecture seule)

**Base :** `/api/v1/sessions/`
**Permissions :** `IsAuthenticated` — list + retrieve.

| Endpoint    | Méthode | Description              |
|-------------|---------|--------------------------|
| `/`         | GET     | Historique des sessions  |
| `{id}/`     | GET     | Détail d'une session     |

**Filtres query string :**
- `?is_active=true|false`
- `?client={lead_id}`
- `?date_from=YYYY-MM-DD&date_to=YYYY-MM-DD`

---

### SessionAnalyticsViewSet (owner)

**Base :** `/api/v1/session-analytics/`
**Permissions :** `IsAuthenticated`
**Cache :** Aucun — les owners veulent la fraîcheur temps réel.

| Endpoint        | Méthode | Description                                  |
|-----------------|---------|----------------------------------------------|
| `overview/`     | GET     | KPIs globaux (sessions, MB, revenus estimés) |
| `by-day/`       | GET     | Sessions par jour (`?days=30`, max 90)       |
| `by-hour/`      | GET     | Répartition par heure (heures de pointe)     |
| `top-clients/`  | GET     | Top 10 clients (sessions, durée, MB)         |

---

## Serializers

### HeartbeatSerializer

Champs requis depuis tracker.js :

| Champ                 | Type      | Source `data-*`         |
|-----------------------|-----------|--------------------------|
| `owner_id`            | int       | injecté côté MikroTik    |
| `mac_address`         | str       | `data-mac`               |
| `ip_address`          | IP        | `data-ip`                |
| `ticket_id`           | str (opt) | `data-ticket`            |
| `mikrotik_session_id` | str (opt) | `data-session-id`        |
| `session_key`         | UUID (opt)| renvoyée par le serveur  |
| `uptime`              | str       | `data-uptime` (`'2h13m'`)|
| `bytes_downloaded`    | int       | `data-bytes-in`          |
| `bytes_uploaded`      | int       | `data-bytes-out`         |
| `download_limit`      | str (opt) | `data-rx-limit`          |
| `upload_limit`        | str (opt) | `data-tx-limit`          |

### EndSessionSerializer

Champ unique : `session_key` (UUID).

### TicketPlanSerializer

Tous les champs du modèle. `owner` en read-only.

### ConnectionSessionSerializer

Lecture seule : tous les champs + `duration_seconds`, `duration_human`,
`total_mb`, `download_mb`, `upload_mb`, `client_email`, `client_phone`,
`ticket_plan_name`, `ticket_plan_price`.

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

Côté tracker.js, un 500 répété arrête les heartbeats et fait perdre la
session. Mieux vaut un 200 silencieux + log Sentry.

### Capturer le user_agent au heartbeat, pas plus tard

Le User-Agent vient du `request.META['HTTP_USER_AGENT']`, pas du payload
JSON (le client peut mentir). Capturé une seule fois (au premier heartbeat).

---

## Admin

`tracking/admin.py` expose les deux modèles avec :
- Actions sur `TicketPlan` : activer / désactiver en masse.
- Actions sur `ConnectionSession` : forcer la fermeture, exporter en CSV.
- Filtres : `is_active`, `owner`, `started_at`.

---

## Structure fichiers

```
tracking/
├── models.py        # TicketPlan + ConnectionSession + parsers MikroTik
├── serializers.py   # Heartbeat, EndSession, TicketPlan, ConnectionSession
├── services.py      # handle_heartbeat, close_session, detect_ticket_plan
├── tasks.py         # cleanup_stale_sessions (Celery)
├── views.py         # 4 ViewSets (Tracking, TicketPlan, Sessions, Analytics)
├── admin.py         # Actions + export CSV
├── tests.py         # 72 tests
└── static/
    └── tracker.js   # Script à intégrer dans status.html / logout.html
```

---

**Documentation mise à jour le 21/04/2026**
