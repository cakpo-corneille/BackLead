# Tracking API — Documentation Frontend

**Version :** 2.0
**Date :** Avril 2026
**Public :** Développeurs Frontend (Dashboard Owner)
**Base URL :** `https://VOTRE_DOMAINE/api/v1/`

---

## Authentification

Tous les endpoints du dashboard nécessitent un JWT :

```
Authorization: Bearer <access_token>
```

Les endpoints `/tracking/heartbeat/` et `/tracking/end/` sont
**publics** (utilisés par le routeur MikroTik) — voir `WIDGET_DOC.md`
pour leur intégration.

---

## 1. Plans tarifaires (TicketPlan)

> ⚠️ **Changement v2.0** — Les champs `download_limit_mb` et
> `upload_limit_mb` ont été supprimés. Un plan se définit désormais
> uniquement par son nom, sa durée et son prix. Retirer ces champs
> de tous les formulaires et affichages.

### GET `/api/v1/ticket-plans/`

Liste des plans de l'owner connecté.

**Réponse 200 :**
```json
[
  {
    "id": 3,
    "name": "Pass 1h",
    "price_fcfa": 200,
    "duration_minutes": 60,
    "is_active": true,
    "created_at": "2026-03-01T10:00:00Z",
    "updated_at": "2026-04-15T14:00:00Z"
  }
]
```

---

### POST `/api/v1/ticket-plans/`

Créer un plan.

**Body :**
```json
{
  "name": "Pass journée",
  "price_fcfa": 1000,
  "duration_minutes": 1440,
  "is_active": true
}
```

---

### PATCH `/api/v1/ticket-plans/{id}/`

Mise à jour partielle. Mêmes champs que POST.

---

### DELETE `/api/v1/ticket-plans/{id}/`

Supprime un plan. Les sessions associées conservent leur référence
historique (`ticket_plan` devient `null`).

---

## 2. Routeurs MikroTik ⭐ Nouveau en v2.0

Cette section est entièrement nouvelle. Elle permet à l'owner de
connecter ses routeurs MikroTik pour que le backend synchronise
les sessions en temps réel, indépendamment du navigateur du client.

> Tant qu'un routeur n'est pas configuré, les sessions sont uniquement
> créées au moment où le client ouvre `status.html`. Avec un routeur
> configuré, Celery maintient les sessions à jour toutes les 2 minutes
> même si le client a fermé son navigateur.

---

### GET `/api/v1/routers/`

Liste des routeurs de l'owner connecté.

**Réponse 200 :**
```json
[
  {
    "id": 1,
    "name": "Boutique principale",
    "host": "192.168.88.1",
    "port": 8728,
    "username": "api-tracker",
    "is_active": true,
    "last_synced_at": "2026-04-25T14:38:00Z",
    "last_error": "",
    "is_healthy": true,
    "created_at": "2026-04-01T09:00:00Z",
    "updated_at": "2026-04-25T14:38:00Z"
  }
]
```

**Champs importants pour l'affichage :**

`is_healthy` — booléen calculé par le backend. Vaut `true` si la
dernière synchro a réussi et qu'il n'y a aucune erreur. C'est le seul
champ dont tu as besoin pour afficher le badge de statut.

`last_error` — message d'erreur lisible en cas de problème de connexion.
À afficher directement à l'owner pour l'aider à corriger sa config.
Exemples : `"Impossible de joindre 192.168.88.1:8728"`,
`"Identifiants refusés par le routeur"`. Vide si tout va bien.

`last_synced_at` — date/heure de la dernière synchronisation réussie.
À afficher sous la forme "il y a X minutes" dans la carte du routeur.

> `password` n'est **jamais retourné** en lecture — ne pas prévoir
> de champ pré-rempli en mode édition. Utiliser un placeholder
> "Laisser vide pour ne pas modifier".

---

### POST `/api/v1/routers/`

Ajouter un routeur.

**Body :**
```json
{
  "name": "Boutique principale",
  "host": "192.168.88.1",
  "port": 8728,
  "username": "api-tracker",
  "password": "motdepasse",
  "is_active": true
}
```

**Réponse 201 :** objet routeur complet sans le champ `password`.

> `password` est obligatoire à la création.

---

### PATCH `/api/v1/routers/{id}/`

Mise à jour partielle. Le champ `password` est optionnel en
modification — s'il est absent du body, le mot de passe existant
est conservé.

---

### DELETE `/api/v1/routers/{id}/`

Supprime le routeur. Prévoir une confirmation obligatoire côté UI.
Les sessions historiques liées sont conservées mais la synchronisation
s'arrête immédiatement.

---

### POST `/api/v1/routers/{id}/test-connection/`

Teste la connexion au routeur et retourne le résultat immédiatement.
À appeler depuis le formulaire de configuration pour valider avant
ou après sauvegarde.

**Réponse 200 — Succès :**
```json
{
  "ok": true,
  "clients_count": 5
}
```

**Réponse 502 — Échec :**
```json
{
  "ok": false,
  "error": "Impossible de joindre 192.168.88.1:8728 — connexion refusée"
}
```

**Conseils d'affichage :**
- Pendant l'appel → spinner sur le bouton, désactiver les autres actions.
- `ok: true` → badge vert "Connexion réussie — X clients actuellement connectés".
- `ok: false` → message rouge avec le contenu de `error` pour guider l'owner.

---

### POST `/api/v1/routers/{id}/sync-now/`

Force une synchronisation immédiate pour ce routeur sans attendre
le cycle Celery (toutes les 2 min). Utile pour tester ou forcer
un rafraîchissement depuis le dashboard.

**Réponse 200 :**
```json
{
  "ok": true,
  "updated": 5,
  "created": 0,
  "closed": 1
}
```

**Conseils d'affichage :**
- Afficher un toast : "Synchro terminée — 5 mises à jour, 1 session fermée".
- Rafraîchir la liste des sessions actives après l'appel.

---

## 3. Sessions WiFi

> ⚠️ **Changement v2.0** — Deux nouveaux champs disponibles :
> `router_name` et `session_timeout_seconds`. Les noms de champs
> dénormalisés ont aussi légèrement changé (voir tableau ci-dessous).

### GET `/api/v1/sessions/`

Historique paginé des sessions.

**Filtres :**
| Paramètre   | Type    | Exemple                  |
|-------------|---------|--------------------------|
| `is_active` | boolean | `?is_active=true`        |
| `client`    | int     | `?client=42`             |
| `date_from` | date    | `?date_from=2026-04-01`  |
| `date_to`   | date    | `?date_to=2026-04-25`    |

**Réponse 200 :**
```json
{
  "count": 1240,
  "next": "...",
  "previous": null,
  "results": [
    {
      "id": 587,
      "client": 42,
      "client_email": "client@example.com",
      "client_phone": "+22997123456",
      "ticket_plan": 3,
      "plan_name": "Pass 4h",
      "plan_price_fcfa": 200,
      "plan_duration_minutes": 240,
      "router_name": "Boutique principale",
      "mac_address": "AA:BB:CC:DD:EE:FF",
      "ip_address": "192.168.88.42",
      "session_key": "f8e7d6c5-b4a3-2109-8765-4321fedcba98",
      "started_at": "2026-04-25T14:32:00Z",
      "ended_at": null,
      "last_heartbeat": "2026-04-25T15:18:42Z",
      "session_timeout_seconds": 14400,
      "uptime_seconds": 2802,
      "duration_seconds": 2802,
      "duration_human": "46m 42s",
      "bytes_downloaded": 145203200,
      "bytes_uploaded": 8421376,
      "download_mb": 138.48,
      "upload_mb": 8.03,
      "total_mb": 146.51,
      "is_active": true,
      "user_agent": "Mozilla/5.0 (Linux; Android 11) ..."
    }
  ]
}
```

---

**Changements de noms de champs v1 → v2 :**

| v1.0                | v2.0                   | Notes                        |
|---------------------|------------------------|------------------------------|
| `ticket_plan_name`  | `plan_name`            | Renommé                      |
| `ticket_plan_price` | `plan_price_fcfa`      | Renommé + devise explicite   |
| *(absent)*          | `plan_duration_minutes`| Nouveau                      |
| *(absent)*          | `router_name`          | Nouveau                      |
| *(absent)*          | `session_timeout_seconds` | Nouveau                   |

> ⚠️ Mettre à jour tous les accès à `ticket_plan_name` et
> `ticket_plan_price` dans le code frontend.

---

**Comment afficher `session_timeout_seconds` :**

C'est la durée totale accordée au ticket — pas le temps consommé.
Elle est fixée dès la connexion et ne change jamais.

```
14400  → "Ticket de 4h"
3600   → "Ticket de 1h"
43200  → "Ticket de 12h"
86400  → "Ticket de 24h"
0      → "Durée illimitée"
```

Afficher en parallèle avec `duration_human` pour donner à l'owner
une vue : durée accordée vs durée réellement consommée.

---

**Logique d'affichage du plan :**

| Situation | Ce qu'il faut afficher |
|---|---|
| `ticket_plan` renseigné | Nom + prix + durée du plan |
| `ticket_plan` null et `session_timeout_seconds` > 0 | Badge jaune "Identification en cours" |
| `ticket_plan` null et `session_timeout_seconds` = 0 | Badge gris "Plan inconnu" |

> En v2.0, les sessions sans plan (`ticket_plan: null`) sont beaucoup
> plus rares qu'en v1.0 car l'identification se fait via `session-timeout`
> qui est disponible dès la première seconde de connexion.

---

**Comment afficher `router_name` :**

Ajouter une colonne "Routeur" dans le tableau historique et une ligne
dans la vue détail. Afficher `—` si `null` (session créée avant la
configuration d'un routeur, ou routeur supprimé depuis).

---

### GET `/api/v1/sessions/{id}/`

Détail d'une session. Mêmes champs que ci-dessus.

---

## 4. Analytics sessions

Aucun endpoint ne change. Seuls les textes explicatifs sont à mettre
à jour.

### GET `/api/v1/session-analytics/overview/`

**Réponse 200 :**
```json
{
  "total_sessions": 1240,
  "sessions_today": 42,
  "sessions_this_week": 287,
  "sessions_this_month": 985,
  "active_sessions": 7,
  "avg_session_seconds": 1840,
  "total_mb": 184523.6,
  "estimated_revenue_today_fcfa": 8400,
  "estimated_revenue_week_fcfa": 57400,
  "estimated_revenue_month_fcfa": 197000
}
```

> Les revenus sont **estimés** à partir des sessions dont le plan a
> été identifié via `session-timeout`. Les sessions sans plan ne sont
> pas comptabilisées. Mettre à jour les tooltips qui mentionnaient
> "rx-limit / tx-limit" en conséquence.

---

### GET `/api/v1/session-analytics/by-day/`

Sessions par jour. Paramètre : `?days=30` (défaut 30, max 90).

**Réponse 200 :**
```json
{
  "labels": ["2026-03-22", "2026-03-23", "..."],
  "data":   [38, 45, 52, 41, 67, "..."]
}
```

---

### GET `/api/v1/session-analytics/by-hour/`

Heures de pointe (24 buckets).

**Réponse 200 :**
```json
{
  "labels": [0, 1, 2, ..., 23],
  "data":   [3, 1, 0, ..., 28, 41, 35, 22]
}
```

---

### GET `/api/v1/session-analytics/top-clients/`

Top 10 clients les plus actifs.

**Réponse 200 :**
```json
[
  {
    "client_id": 42,
    "email": "client@example.com",
    "phone": "+22997123456",
    "mac_address": "AA:BB:CC:DD:EE:FF",
    "sessions_count": 87,
    "total_seconds": 142800,
    "total_mb": 12483.5
  }
]
```

---

## 5. Codes HTTP

| Code | Signification                                      |
|------|----------------------------------------------------|
| 200  | Succès                                             |
| 201  | Ressource créée (plan, routeur)                    |
| 204  | Ressource supprimée                                |
| 400  | Erreur de validation                               |
| 401  | Non authentifié                                    |
| 403  | Tentative cross-owner                              |
| 404  | Ressource introuvable                              |
| 429  | Rate limit dépassé (heartbeats publics)            |
| 502  | Routeur MikroTik injoignable (test-connection)     |

---

## 6. Détection automatique du plan

> ⚠️ **Changement v2.0** — La logique a complètement changé.

**Avant (v1.0)** — Le plan était identifié en comparant les limites
`rx-limit` / `tx-limit` MikroTik aux champs `download_limit_mb` /
`upload_limit_mb` du plan.

**Maintenant (v2.0)** — Le plan est identifié en comparant
`$(session-timeout)` MikroTik (durée totale du ticket) au champ
`duration_minutes` du plan. Cette valeur est disponible dès la première
seconde de connexion, sans aucune configuration supplémentaire sur MikroTik.

**Conséquences pour le frontend :**
- Retirer toute mention de "limites rx/tx" dans les tooltips et textes.
- Le badge "Plan inconnu" est désormais rare — l'afficher uniquement
  si `ticket_plan` est `null` ET `session_timeout_seconds` vaut `0`.
- Si plusieurs plans ont la même durée → le plan dont la durée est la
  plus proche est retenu.

---

## 7. Conseils d'intégration

- Pour le dashboard temps réel, **ne mettez pas en cache** ces endpoints.
  Poll toutes les 30-60 s sur `overview/` pour les KPIs.
- Pour surveiller l'état des routeurs, poll toutes les 60 s sur
  `GET /api/v1/routers/` et afficher `is_healthy` + `last_error`.
- Pour l'historique long, paginez (`?page=2&page_size=50`) et utilisez
  `date_from` / `date_to` pour limiter la fenêtre.
- Le champ `is_active` bascule maintenant à `False` dès que MikroTik
  ne liste plus le client (synchro Celery toutes les 2 min), ou après
  10 min sans heartbeat si le routeur est hors ligne.
- Après un appel `sync-now/` réussi, rafraîchir la liste des sessions
  actives pour refléter l'état réel immédiatement.

---

**Documentation mise à jour le 26/04/2026**
