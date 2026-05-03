# Tracking App — Documentation Backend

**Version :** 1.1
**Date :** Avril 2026
**Public :** Développeurs Backend, DevOps, Maintenance

---

## Architecture

L'application `tracking` capture et expose les **sessions WiFi** des clients connectés à un hotspot MikroTik. Elle reçoit des heartbeats publics depuis `tracker.js` (intégré dans `status.html` / `logout.html` sur le routeur), associe chaque session à un `OwnerClient` et à un `TicketPlan` quand c'est possible, et fournit une API analytics au dashboard owner.

**Composants :**
- 2 modèles : `TicketPlan` (catalogue tarifaire) + `ConnectionSession` (sessions actives/historiques)
- Endpoints publics rate-limités pour les heartbeats
- Endpoints owner authentifiés : CRUD plans, historique, analytics
- Tâche Celery périodique de fermeture des sessions zombies
- Détection automatique du plan via les limites MikroTik (`rx-limit` / `tx-limit`)

---

## Modèles

### TicketPlan

Plan tarifaire déclaré par l'owner depuis son dashboard. Sert de référence pour identifier automatiquement quel plan correspond à une session MikroTik via les limites de données ou la durée.

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
- `download_limit_bytes` / `upload_limit_bytes` : conversion MB → bytes (ou `None` si illimité).

**Index :**
- `(owner, is_active)` — filtrage rapide des plans actifs pour le matching.

---

### ConnectionSession

Une session = un ticket WiFi = une connexion d'un client. Même client, tickets différents → sessions différentes. Mise à jour à chaque heartbeat (refresh MikroTik de `status.html`).

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

    # Consommation (mise à jour à chaque heartbeat)
    uptime_seconds       = PositiveIntegerField(default=0)
    bytes_downloaded     = BigIntegerField(default=0)
    bytes_uploaded       = BigIntegerField(default=0)
    download_limit_bytes = BigIntegerField(null=True, blank=True)
    upload_limit_bytes   = BigIntegerField(null=True, blank=True)

    is_active     = BooleanField(default=True, db_index=True)
    user_agent    = CharField(max_length=512, blank=True, default='')
    last_raw_data = JSONField(default=dict, blank=True)  # snapshot heartbeat brut
```

**Propriétés calculées :**
- `duration_seconds` → utilise `ended_at` si défini, sinon `uptime_seconds`.
- `duration_human` → format lisible `"1h 23m 45s"`.
- `total_mb`, `download_mb`, `upload_mb`.

**Index :**
- `(owner, -started_at)` — tri chronologique par owner.
- `(owner, mac_address)` — lookup session par appareil.
- `(owner, is_active)` — sessions actives en temps réel.

---

## Helpers de parsing MikroTik

**Fichier :** `tracking/models.py`

### `parse_mikrotik_uptime(s)`

Convertit `'1d2h34m56s'` en secondes. Les unités nulles sont omises par MikroTik (`'5m12s'`, `'2h3s'` sont valides). Retourne `0` pour toute valeur invalide.

```python
parse_mikrotik_uptime('1d2h34m56s')  # → 95696
parse_mikrotik_uptime('5m12s')       # → 312
parse_mikrotik_uptime('')            # → 0
```

### `parse_mikrotik_limit(s)`

Convertit `'10M'` / `'512k'` / `'2G'` en bytes. Retourne `None` pour `'---'`, `''` ou `'0'` (illimité).

```python
parse_mikrotik_limit('10M')   # → 10485760
parse_mikrotik_limit('512k')  # → 524288
parse_mikrotik_limit('---')   # → None
```

---

## Services métier

**Fichier :** `tracking/services.py`

### `handle_heartbeat(data, user_agent='')`

Point d'entrée unique pour un heartbeat tracker. Crée la session si elle n'existe pas, la met à jour sinon.

**Logique :**
1. Si `session_key` fourni → cherche la session existante et applique `_apply_heartbeat`.
2. Si session inconnue ou `session_key` absent → résout l'owner via `public_key` (FormSchema).
3. Résout le client via `(owner, mac_address)` — **le client doit exister** (créé par le widget avant le tracker).
4. Crée la `ConnectionSession` et tente le matching `TicketPlan` via `match_ticket_plan`.
5. Capture le `user_agent` au premier heartbeat uniquement.

**Returns :** `(session: ConnectionSession, created: bool)`

**Raises :**
- `ValueError` si `public_key` inconnu.
- `ValueError` si client introuvable pour cette MAC (le widget n'a pas encore été soumis).

> **Ordre inviolable :** Le widget (`widget.js`) doit toujours avoir enregistré le client avant que `tracker.js` n'envoie le premier heartbeat. Si le client est absent, la session ne peut pas être créée.

---

### `_apply_heartbeat(session, data)`

Applique les données fraîches d'un heartbeat sur une session existante. Met à jour `uptime_seconds`, `bytes_downloaded`, `bytes_uploaded`, `is_active`, et `last_raw_data`.

Sérialise les types non-JSON (UUID, datetime) en string avant de stocker dans `last_raw_data`.

---

### `match_ticket_plan(owner, download_limit_bytes, upload_limit_bytes, uptime_seconds)`

Identifie le `TicketPlan` correspondant à une session.

**Stratégie :**
1. Si `rx-limit` / `tx-limit` présents → match strict par égalité de bytes.
2. Si limites illimitées → fallback par durée la plus proche (`duration_minutes * 60` vs `uptime_seconds`).

**Returns :** `TicketPlan | None`

> Le fallback par durée est imprécis en début de session (le client n'a consommé qu'une fraction). Il devient pertinent à mi-parcours et au-delà.

---

### `close_session(session_key)`

Ferme proprement une session : `is_active=False`, `ended_at=now()`. Idempotent (retourne `0` si déjà fermée).

**Returns :** `int` — nombre de sessions effectivement fermées (0 ou 1).

---

### `close_stale_sessions(threshold_minutes=10)`

Marque comme terminées toutes les sessions sans heartbeat depuis `threshold_minutes`. L'heure de fin est positionnée à `last_heartbeat` (approximation au plus juste).

**Attention :** Actuellement implémenté avec une boucle Python + `session.save()`. À migrer vers un `bulk_update` pour la scalabilité.

```python
# À venir — version optimisée
ConnectionSession.objects.filter(
    is_active=True,
    last_heartbeat__lt=cutoff,
).update(is_active=False, ended_at=F('last_heartbeat'))
```

---

## Tâches Celery

### `tracking.cleanup_stale_sessions`

Ferme automatiquement les sessions dont le dernier heartbeat date de plus de **10 minutes** (sessions zombies — client disparu sans logout). MikroTik rafraîchit `status.html` toutes les ~60s, donc 10 minutes sans signal = déconnexion certaine.

**Schedule :** toutes les **5 minutes** (`CELERY_BEAT_SCHEDULE` dans `config/base.py`).

```python
CELERY_BEAT_SCHEDULE = {
    'tracking-cleanup-stale-sessions': {
        'task': 'tracking.cleanup_stale_sessions',
        'schedule': timedelta(minutes=5),
    },
}
```

---

## ViewSets & Endpoints

### TrackingViewSet (public)

**Base :** `/api/v1/tracking/`
**Permissions :** `AllowAny`
**Rate limit :** 30 requêtes / 60 s par IP (sur `heartbeat/`)

| Endpoint     | Méthode | Description                                  |
|--------------|---------|----------------------------------------------|
| `heartbeat/` | POST    | Reçoit un heartbeat depuis tracker.js        |
| `end/`       | POST    | Ferme une session (sendBeacon depuis logout)  |

> **Politique d'erreur sur `heartbeat/` :** Ne renvoie **jamais 500** — en cas d'exception interne, on log silencieusement et on retourne `200 {"ok": false}`. Un 500 répété arrête les heartbeats et fait perdre la session côté tracker.

---

### TicketPlanViewSet (owner)

**Base :** `/api/v1/ticket-plans/`
**Permissions :** `IsAuthenticated` (CRUD complet)

| Endpoint    | Méthode                    | Description                      |
|-------------|----------------------------|----------------------------------|
| `/`         | GET / POST                 | Liste / créer un plan            |
| `{id}/`     | GET / PUT / PATCH / DELETE | Détail / éditer / supprimer      |

`owner` est forcé via `perform_create` — jamais lisible ni modifiable côté client.

---

### ConnectionSessionViewSet (owner, lecture seule)

**Base :** `/api/v1/sessions/`
**Permissions :** `IsAuthenticated` — list + retrieve.

| Endpoint | Méthode | Description              |
|----------|---------|--------------------------|
| `/`      | GET     | Historique des sessions  |
| `{id}/`  | GET     | Détail d'une session     |

**Filtres query string :**
- `?is_active=true|false`
- `?client={owner_client_id}`
- `?date_from=YYYY-MM-DD&date_to=YYYY-MM-DD`

---

### SessionAnalyticsViewSet (owner)

**Base :** `/api/v1/session-analytics/`
**Permissions :** `IsAuthenticated`
**Cache :** Aucun — données fraîches voulues par les owners.

| Endpoint       | Méthode | Description                                     |
|----------------|---------|-------------------------------------------------|
| `overview/`    | GET     | KPIs globaux (sessions, MB, revenus estimés)    |
| `by-day/`      | GET     | Sessions par jour (`?days=30`, max 90)          |
| `by-hour/`     | GET     | Répartition par heure de la journée (24h)       |
| `top-clients/` | GET     | Top 10 clients (nb sessions, durée, MB)         |

---

## Serializers

### HeartbeatSerializer

Champs envoyés par `tracker.js` depuis le routeur MikroTik :

| Champ        | Type      | Source MikroTik         | Requis |
|--------------|-----------|-------------------------|--------|
| `public_key` | UUID      | injecté dans le snippet | ✓      |
| `mac_address`| str       | `$(mac)`                | ✓      |
| `session_key`| UUID      | retourné par l'API      | —      |
| `ip_address` | IP        | `$(ip)`                 | —      |
| `uptime`     | str       | `$(uptime)` (`'2h13m'`) | —      |
| `bytes_in`   | str/int   | `$(rx-bytes)`           | —      |
| `bytes_out`  | str/int   | `$(tx-bytes)`           | —      |
| `rx_limit`   | str       | `$(rx-limit-at)`        | —      |
| `tx_limit`   | str       | `$(tx-limit-at)`        | —      |
| `username`   | str       | `$(username)` (ticket)  | —      |
| `session_id` | str       | `$(session-id)`         | —      |

### EndSessionSerializer

Champ unique : `session_key` (UUID).

### TicketPlanSerializer

Tous les champs du modèle. `owner` en read-only.

### ConnectionSessionSerializer

Lecture seule. Champs calculés exposés en plus des champs modèle :

| Champ calculé    | Source                           |
|------------------|----------------------------------|
| `duration_seconds` | propriété modèle               |
| `duration_human`   | propriété modèle               |
| `total_mb`         | propriété modèle               |
| `download_mb`      | propriété modèle               |
| `upload_mb`        | propriété modèle               |
| `plan_name`        | `ticket_plan.name`             |
| `plan_price_fcfa`  | `ticket_plan.price_fcfa`       |
| `client_email`     | `client.email`                 |
| `client_phone`     | `client.phone`                 |

---

## Commande de peuplement

```bash
# Peupler avec les valeurs par défaut (150 sessions)
python manage.py populate_tracking --settings=config.settings

# Peupler avec plus de sessions
python manage.py populate_tracking --sessions 500 --settings=config.settings

# Repartir de zéro
python manage.py populate_tracking --clear --sessions 300 --settings=config.settings
```

**Prérequis :** Les apps `accounts` et `core_data` doivent être peuplées en premier.

```bash
python manage.py populate_accounts
python manage.py populate_core_data
python manage.py populate_tracking
```

**Ce que la commande génère :**
- 2 à 5 `TicketPlan` par owner, tirés du catalogue tarifaire réaliste (Pass 30 min à Pass Semaine)
- Sessions réparties sur 90 jours avec pondération vers les 30 derniers jours
- Heures de connexion pondérées vers les pics réels (soirée 18h–23h)
- `uptime_seconds` cohérent avec la durée du plan (± 20%)
- `bytes_downloaded` / `bytes_uploaded` cohérents avec l'uptime
- ~40% des sessions récentes (< 2h) laissées actives (`is_active=True`)
- ~85% des sessions associées à un `TicketPlan`, ~15% sans plan détecté
- `user_agent` réalistes (appareils Tecno, Samsung, itel, iPhone — parc mobile Afrique de l'Ouest)
- `last_raw_data` snapshot réaliste au format heartbeat MikroTik

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
    session, created = handle_heartbeat(serializer.validated_data, ...)
    return Response({'ok': True, 'session_key': str(session.session_key)})
except ValueError as e:
    return Response({'detail': str(e)}, status=400)
except Exception:
    logger.exception("Heartbeat error")
    return Response({'ok': False}, status=200)  # Jamais 500
```

### Utiliser `update_fields` sur `_apply_heartbeat`

Chaque heartbeat ne doit mettre à jour que les champs qui changent, pas tout le modèle :

```python
session.save(update_fields=[
    'uptime_seconds', 'bytes_downloaded', 'bytes_uploaded',
    'is_active', 'last_raw_data'
])
```

### Le widget avant le tracker — ordre inviolable

`widget.js` (soumission du formulaire) doit toujours avoir été exécuté avant que `tracker.js` ne démarre les heartbeats. Sans `OwnerClient` correspondant à la MAC, `handle_heartbeat` lève une `ValueError` et la session n'est pas créée.

---

## Admin

`tracking/admin.py` expose les deux modèles avec :

**TicketPlanAdmin :**
- Affichage : email owner, prix formaté FCFA, durée lisible, limites D/U, nombre de sessions liées
- Actions bulk : activer / désactiver en masse
- Filtres : `is_active`, `owner`, `created_at`

**ConnectionSessionAdmin :**
- Affichage : clé courte, owner, client (email/phone/mac), IP, plan, durée, data D/U, badge statut coloré
- Actions bulk : forcer la fermeture, exporter en CSV
- Filtres : `is_active`, `owner`, `ticket_plan`, date de début
- Recherche : MAC, IP, ticket_id, session_key, email/phone client, email owner
- Section `last_raw_data` en accordéon (collapse)

---

## Problèmes connus et points d'amélioration

| Problème | Impact | Recommandation |
|---|---|---|
| `close_stale_sessions` : boucle Python + `session.save()` | N requêtes SQL | Migrer vers `bulk_update` |
| `_apply_heartbeat` sans `update_fields` | Sauvegarde tous les champs | Ajouter `update_fields` |
| `match_ticket_plan` (fallback durée) en début de session | Matching imprécis | Matcher en fin de session ou sur les limites uniquement |
| `TrackingViewSet.end` sans rate limit | Fermeture abusive possible | Ajouter `ratelimit_public_api` |

---

## Structure fichiers

```
tracking/
├── models.py          # TicketPlan + ConnectionSession + parsers MikroTik
├── serializers.py     # Heartbeat, EndSession, TicketPlan, ConnectionSession
├── services.py        # handle_heartbeat, close_session, match_ticket_plan
├── tasks.py           # cleanup_stale_sessions (Celery Beat)
├── views.py           # 4 ViewSets : Tracking, TicketPlan, Sessions, Analytics
├── admin.py           # Actions bulk + export CSV
├── tests.py
├── migrations/
└── static/
    ├── tracker.js       # Script status.html / logout.html (non minifié)
    └── tracker.min.js   # Version minifiée pour la production
```

---

**Documentation mise à jour le 22/04/2026**
