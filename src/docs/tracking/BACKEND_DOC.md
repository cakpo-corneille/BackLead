# Tracking App — Documentation Backend

**Version :** 3.0
**Date :** Mai 2026
**Public :** Développeurs backend, DevOps, maintenance

---

## Vue d'ensemble

L'app `tracking` gère les sessions WiFi des clients connectés à un hotspot MikroTik. Elle sait qui est connecté, depuis combien de temps, combien de données a été consommée, quel plan tarifaire a été utilisé, et combien ça a rapporté.

Le principe central est simple : **c'est le routeur MikroTik qui contacte le backend, jamais l'inverse.** Deux scripts RouterOS (`on-login` / `on-logout`) envoient un POST HTTP à chaque événement de connexion ou déconnexion. Il n'y a ni polling, ni heartbeat navigateur, ni connexion directe à l'API RouterOS depuis le serveur.

```
Client achète un ticket WiFi
    → MikroTik valide le ticket
    → script on-login  → POST /api/v1/sessions/login/   → crée ConnectionSession
    → client navigue (rien ne se passe côté backend)
    → ticket expire ou client se déconnecte
    → script on-logout → POST /api/v1/sessions/logout/  → ferme ConnectionSession
```

Celery Beat tourne en parallèle toutes les 10 minutes comme filet de sécurité : il ferme les sessions dont `on-logout` n'est jamais arrivé (coupure courant, crash routeur).

---

## Composants

- **2 modèles** : `TicketPlan` + `ConnectionSession`
- **2 endpoints publics** (AllowAny, throttlés) : login et logout MikroTik
- **3 endpoints owner** authentifiés : CRUD plans, historique sessions, analytics
- **1 tâche Celery** : fermeture des sessions expirées (filet de sécurité)
- **Identification automatique** du plan via `$(uptime-limit)` MikroTik

---

## Modèles

### TicketPlan

Les plans tarifaires déclarés par chaque gérant. L'identification automatique du plan d'une session se fait en comparant `session_timeout_seconds` (la durée du ticket envoyée par MikroTik) au champ `duration_minutes * 60`.

```python
class TicketPlan(models.Model):
    owner            = ForeignKey(User, related_name='ticket_plans')
    name             = CharField(max_length=100)
    price_fcfa       = PositiveIntegerField()
    duration_minutes = PositiveIntegerField()  # 60 pour 1h, 240 pour 4h, etc.
    is_active        = BooleanField(default=True)
    created_at       = DateTimeField(auto_now_add=True)
    updated_at       = DateTimeField(auto_now=True)
```

Le matching est **exact** : `duration_minutes * 60 == session_timeout_seconds`. Si aucun plan ne correspond exactement, la session est créée sans plan (`ticket_plan=None`). Il n'y a plus de logique d'approximation — une session dont le timeout ne correspond à aucun plan reste sans plan plutôt que d'être mal attribuée.

---

### ConnectionSession

Une session représente un ticket WiFi consommé. Elle est créée par `on-login` et fermée par `on-logout` ou par la tâche Celery.

```python
class ConnectionSession(models.Model):
    # Relations
    owner       = ForeignKey(User, related_name='tracking_sessions')
    client      = ForeignKey(OwnerClient, related_name='sessions')
    ticket_plan = ForeignKey(TicketPlan, null=True, blank=True, on_delete=SET_NULL)

    # Identifiants réseau
    mac_address         = CharField(max_length=17, db_index=True)
    ip_address          = GenericIPAddressField(null=True, blank=True)
    ticket_id           = CharField(max_length=128, null=True, blank=True)
    mikrotik_session_id = CharField(max_length=128, null=True, blank=True, db_index=True)
    session_key         = UUIDField(default=uuid.uuid4, unique=True, db_index=True)

    # Timing
    started_at     = DateTimeField(auto_now_add=True)
    ended_at       = DateTimeField(null=True, blank=True)
    last_heartbeat = DateTimeField(auto_now=True)

    # Durée totale du ticket ($uptime-limit) — clé d'identification du plan
    session_timeout_seconds = PositiveIntegerField(default=0)

    # Consommation réelle (renseignée par on-logout)
    uptime_seconds   = PositiveIntegerField(default=0)
    bytes_downloaded = BigIntegerField(default=0)
    bytes_uploaded   = BigIntegerField(default=0)

    # Revenu
    amount_fcfa = PositiveIntegerField(default=0)  # copie figée de plan.price_fcfa au login

    # État
    is_active        = BooleanField(default=True, db_index=True)
    disconnect_cause = CharField(max_length=64, blank=True, default='')
```

Quelques points importants :

**`mikrotik_session_id`** est la clé de rapprochement entre `on-login` et `on-logout`. C'est le `$session-id` envoyé par MikroTik. Sans lui, on ne peut pas retrouver quelle session fermer.

**`amount_fcfa`** est une copie figée du prix du plan au moment du login. Ça protège l'historique financier si le gérant modifie ses prix par la suite.

**`disconnect_cause`** reprend la valeur `$cause` envoyée par MikroTik : `session-timeout`, `lost-service`, `logout`, `dropped`. La valeur `expired-by-server` est réservée aux sessions fermées par la tâche Celery.

---

### Propriété `status` (calculée)

Le modèle expose une propriété `status` qui synthétise `is_active` et `disconnect_cause` en une valeur lisible. C'est ce champ qui est exposé dans le serializer — `is_active` et `disconnect_cause` ne sont pas retournés directement dans l'API.

| Condition | Valeur retournée |
|---|---|
| `is_active = True` | `'connecté'` |
| `is_active = False` + `disconnect_cause = 'expired-by-server'` | `'expiré'` |
| `is_active = False` + autre cause | `'déconnecté'` |

---

## Flux de données MikroTik

### Données reçues au login

```
mac          $mac              DC:A6:32:AA:BB:CC
ip           $ip               192.168.88.105
user         $user             ticket_abc123
session_id   $session-id       *1A2B3C
uptime_limit $uptime-limit     1h  (ou 4h, 30m, etc.)
owner_key    (ajouté script)   uuid-du-gérant
```

### Données reçues au logout

```
mac          $mac              DC:A6:32:AA:BB:CC
session_id   $session-id       *1A2B3C
uptime       $uptime           54m12s
bytes_in     $bytes-in         45234567
bytes_out    $bytes-out        1234567
cause        $cause            session-timeout
owner_key    (ajouté script)   uuid-du-gérant
```

---

## Logique métier

**Fichier :** `tracking/hotspot_service.py`

### `validate_owner_key(owner_key)`

Retrouve l'owner via `FormSchema.public_key`. Lève `ValueError` si la clé est invalide ou inconnue. C'est le point d'entrée de toutes les requêtes publiques MikroTik.

### `handle_login(owner, data)`

1. Normalise l'adresse MAC.
2. Cherche le `OwnerClient` correspondant au MAC. Si le client est inconnu (il n'a pas rempli le formulaire du portail), retourne `None` sans créer de session.
3. Met à jour `client.last_seen = timezone.now()`.
4. Parse `uptime_limit` (format MikroTik comme `'1h'`, `'30m'`) en secondes.
5. Crée la `ConnectionSession`.
6. Appelle `match_ticket_plan()` pour identifier le plan.
7. Si un plan est trouvé, renseigne `session.ticket_plan` et `session.amount_fcfa`.

### `handle_logout(owner, data)`

1. Retrouve la session via `mikrotik_session_id`.
2. Met à jour `uptime_seconds`, `bytes_downloaded`, `bytes_uploaded`, `disconnect_cause`.
3. Passe `is_active` à `False` et renseigne `ended_at`.
4. Met à jour `client.last_seen = timezone.now()`.

### `close_expired_sessions()`

Filet de sécurité Celery. Cherche toutes les sessions actives dont `started_at + session_timeout_seconds + 10 min <= now`. Pour chaque session expirée, passe `is_active = False`, renseigne `ended_at = now` et `disconnect_cause = 'expired-by-server'`. Utilise un `UPDATE` groupé sur les IDs pour ne faire qu'une seule requête SQL.

---

## Services utilitaires

**Fichier :** `tracking/services.py`

### `match_ticket_plan(owner, session_timeout_seconds)`

Cherche parmi les plans actifs de l'owner celui dont `duration_minutes * 60 == session_timeout_seconds`. Le matching est strictement exact — aucune approximation. Si `session_timeout_seconds` est nul ou négatif, retourne `None` directement sans interroger la base.

### `close_session(session, cause='')`

Ferme une session proprement : `is_active = False`, `ended_at = now`, `disconnect_cause` renseigné. Utilisé par `handle_logout` et les tests.

---

## Signaux

**Fichier :** `tracking/signals.py`

Un signal `post_save` sur `ConnectionSession` déclenche deux effets :

- **À la création** (`created=True`) : incrémente `client.recognition_level` de 1. Ce champ mesure la fidélité du client — combien de fois il est revenu.
- **À la création ou à la fermeture** (quand `is_active` passe à `False`) : appelle `invalidate_analytics_cache(owner_id)` pour vider le cache des stats du dashboard.

Les signaux sont branchés dans `TrackingConfig.ready()` dans `apps.py`.

---

## Tâche Celery

**Fichier :** `tracking/tasks.py`

### `close_expired_sessions`

Délègue à `hotspot_service.close_expired_sessions()`. Planifiée toutes les **10 minutes** dans `CELERY_BEAT_SCHEDULE`. Ne doit jamais être le mécanisme principal de fermeture — c'est uniquement un filet pour les `on-logout` jamais reçus.

```python
# config/base.py
CELERY_BEAT_SCHEDULE = {
    'close-expired-sessions': {
        'task': 'tracking.close_expired_sessions',
        'schedule': 600,  # 10 minutes
    },
}
```

---

## Endpoints

### Endpoints publics — MikroTik

Ces deux endpoints sont appelés directement par les scripts RouterOS. Pas de JWT, `AllowAny`, throttle dédié `hotspot` à 200 req/min.

**`POST /api/v1/sessions/login/`**
Reçoit les données `on-login`. Crée la session. Ne renvoie jamais 500 — en cas d'erreur interne, log silencieux.

**`POST /api/v1/sessions/logout/`**
Reçoit les données `on-logout`. Ferme la session correspondante. Même règle : jamais de 500.

---

### Endpoints owner — Dashboard

Tous nécessitent `Authorization: Bearer <token>`. Chaque queryset est filtré par `owner=request.user` — un gérant ne peut jamais voir les données d'un autre.

**`/api/v1/ticket-plans/`** — CRUD complet sur les plans tarifaires.

**`/api/v1/sessions/`** — Lecture seule. Filtres disponibles : `?is_active=true|false`, `?client={id}`, `?date_from=YYYY-MM-DD`, `?date_to=YYYY-MM-DD`.

**`/api/v1/session-analytics/`** — 4 actions : `overview/`, `by-day/`, `by-hour/`, `top-clients/`.

---

## Serializers

### `HotspotLoginSerializer`

Valide les champs envoyés par `on-login` : `mac`, `ip`, `user`, `session_id`, `uptime_limit`, `owner_key`. Normalise automatiquement l'adresse MAC en majuscules avec deux-points.

### `HotspotLogoutSerializer`

Valide les champs envoyés par `on-logout` : `mac`, `session_id`, `uptime`, `cause`, `owner_key`, `bytes_in`, `bytes_out`. Les champs bytes ont `default='0'` pour tolérer les routeurs qui ne les envoient pas toujours.

### `TicketPlanSerializer`

Champs : `id`, `name`, `price_fcfa`, `duration_minutes`, `is_active`, `created_at`, `updated_at`. Valide que `price_fcfa >= 0` et `duration_minutes > 0`.

### `ConnectionSessionSerializer`

Lecture seule. Expose `status` (calculé) à la place de `is_active` et `disconnect_cause`. Inclut les champs calculés `duration_seconds`, `duration_human`, `total_mb`, `download_mb`, `upload_mb` et les champs dénormalisés `plan_name`, `plan_price_fcfa`, `plan_duration_minutes`, `client_email`, `client_phone`.

### `get_tracking_snippet(owner_key, request)`

Génère les 2 scripts RouterOS prêts à coller dans WinBox (`on_login`, `on_logout`). L'URL du backend est dérivée dynamiquement depuis `request.build_absolute_uri('/')`. Retourne un dict avec les clés `on_login` et `on_logout`.

---

## Configuration requise

### Throttle hotspot

Les endpoints publics MikroTik utilisent `throttle_scope = 'hotspot'`. Ce scope doit être déclaré dans `config/base.py` :

```python
REST_FRAMEWORK = {
    ...
    'DEFAULT_THROTTLE_CLASSES': [
        'rest_framework.throttling.ScopedRateThrottle',
    ],
    'DEFAULT_THROTTLE_RATES': {
        'hotspot': '200/minute',
    },
}
```

Sans cette ligne, le premier appel en production lève une erreur de configuration.

---

## Sécurité et isolation

Chaque queryset dans les ViewSets est filtré par `owner=request.user`. C'est la règle absolue — ne jamais utiliser `.all()` sur un endpoint dashboard. Un gérant qui manipule les IDs dans les URLs doit recevoir un 404, jamais les données d'un autre gérant.

Les endpoints publics (`login/`, `logout/`) ne renvoient jamais de 500. Toute exception interne est loggée silencieusement et l'endpoint répond `200 {"ok": false}`. Le routeur MikroTik ne doit pas être bloqué par une erreur backend.

---

## Structure des fichiers

```
tracking/
├── models.py          # TicketPlan + ConnectionSession (@property status)
├── hotspot_service.py # handle_login, handle_logout, close_expired_sessions
├── services.py        # match_ticket_plan, close_session
├── serializers.py     # Serializers MikroTik + Dashboard + get_tracking_snippet
├── views.py           # 4 ViewSets (login, logout, plans, sessions, analytics)
├── tasks.py           # Tâche Celery close_expired_sessions
├── signals.py         # post_save ConnectionSession → recognition_level + cache
├── apps.py            # TrackingConfig.ready() branche les signaux
├── admin.py
├── tests.py
└── migrations/
```

---

**Documentation mise à jour le 02/05/2026**
