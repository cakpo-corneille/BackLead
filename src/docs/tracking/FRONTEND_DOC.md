# Tracking API — Documentation Frontend

**Version :** 1.0
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
    "download_limit_mb": 1024,
    "upload_limit_mb": 256,
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
  "download_limit_mb": null,
  "upload_limit_mb": null,
  "is_active": true
}
```

> Laissez `download_limit_mb` / `upload_limit_mb` à `null` pour illimité.

---

### PATCH `/api/v1/ticket-plans/{id}/`

Mise à jour partielle. Mêmes champs que POST.

### DELETE `/api/v1/ticket-plans/{id}/`

Supprime un plan. Les sessions associées conservent leur référence
historique (`ticket_plan` devient `null`).

---

## 2. Sessions WiFi

### GET `/api/v1/sessions/`

Historique paginé des sessions.

**Filtres :**
| Paramètre   | Type    | Exemple                  |
|-------------|---------|--------------------------|
| `is_active` | boolean | `?is_active=true`        |
| `client`    | int     | `?client=42`             |
| `date_from` | date    | `?date_from=2026-04-01`  |
| `date_to`   | date    | `?date_to=2026-04-21`    |

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
      "ticket_plan_name": "Pass 1h",
      "ticket_plan_price": 200,
      "mac_address": "AA:BB:CC:DD:EE:FF",
      "ip_address": "192.168.88.42",
      "session_key": "f8e7d6c5-b4a3-2109-8765-4321fedcba98",
      "started_at": "2026-04-21T14:32:00Z",
      "ended_at": null,
      "last_heartbeat": "2026-04-21T15:18:42Z",
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

### GET `/api/v1/sessions/{id}/`

Détail d'une session (mêmes champs que ci-dessus).

---

## 3. Analytics sessions

### GET `/api/v1/session-analytics/overview/`

Vue d'ensemble du dashboard.

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

> Les revenus sont **estimés** à partir des sessions associées à un
> `TicketPlan`. Les sessions sans plan détecté ne sont pas comptabilisées.

---

### GET `/api/v1/session-analytics/by-day/`

Sessions par jour.

**Paramètre :** `?days=30` (défaut 30, max 90).

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

## 4. Codes HTTP

| Code | Signification                              |
|------|--------------------------------------------|
| 200  | Succès                                     |
| 201  | Plan créé / session créée                  |
| 204  | Plan supprimé                              |
| 400  | Erreur de validation                       |
| 401  | Non authentifié                            |
| 403  | Tentative cross-owner                      |
| 404  | Ressource introuvable                      |
| 429  | Rate limit dépassé (heartbeats publics)    |

---

## 5. Détection automatique du plan

Le backend essaie d'associer chaque session à un `TicketPlan` en
comparant les limites MikroTik (`rx-limit` / `tx-limit`) à
`download_limit_mb` / `upload_limit_mb` du plan.

**Conséquences pour le frontend :**
- Affichez un badge "Plan inconnu" si `ticket_plan` est `null`.
- Si plusieurs plans ont les mêmes limites → le premier `is_active=True` est retenu.
- En cas de session illimitée, c'est `duration_minutes` qui est utilisé.

---

## 6. Conseils d'intégration

- Pour le dashboard temps réel, **ne mettez pas en cache** ces endpoints
  côté frontend (le backend ne le fait pas non plus). Faites un poll
  toutes les 30-60 s sur `overview/` pour les KPIs.
- Pour l'historique long, paginez (`?page=2&page_size=50`) et utilisez
  `date_from`/`date_to` pour limiter la fenêtre.
- Le champ `is_active` peut basculer à `False` automatiquement après
  15 min sans heartbeat (tâche Celery `cleanup_stale_sessions`).

---

**Documentation mise à jour le 21/04/2026**
