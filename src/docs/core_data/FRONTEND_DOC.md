# Tracking API — Documentation Frontend

**Version :** 1.1
**Date :** Avril 2026
**Public :** Développeurs Frontend (Dashboard Owner)
**Base URL :** `https://VOTRE_DOMAINE/api/v1/`

---

## Authentification

Tous les endpoints du dashboard nécessitent un JWT :

```
Authorization: Bearer <access_token>
```

Les endpoints `/tracking/heartbeat/` et `/tracking/end/` sont **publics** (utilisés par le routeur MikroTik via `tracker.js`) — leur intégration est documentée dans `WIDGET_DOC.md`.

---

## 1. Plans tarifaires — TicketPlan

Les plans tarifaires permettent au dashboard d'afficher des revenus estimés et d'annoter chaque session avec son ticket correspondant. Ils doivent refléter exactement les tarifs configurés dans MikroTik pour que la détection automatique fonctionne.

---

### `GET /api/v1/ticket-plans/`

Liste des plans de l'owner connecté, triés par prix croissant.

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
  },
  {
    "id": 4,
    "name": "Pass Journée",
    "price_fcfa": 1000,
    "duration_minutes": 1440,
    "download_limit_mb": null,
    "upload_limit_mb": null,
    "is_active": true,
    "created_at": "2026-03-01T10:00:00Z",
    "updated_at": "2026-04-15T14:00:00Z"
  }
]
```

> `download_limit_mb` / `upload_limit_mb` à `null` = illimité.

---

### `POST /api/v1/ticket-plans/`

Créer un plan. Les limites doivent correspondre exactement aux valeurs configurées dans MikroTik (`rx-limit` / `tx-limit`) pour que la détection automatique fonctionne.

**Body :**
```json
{
  "name": "Pass 3h",
  "price_fcfa": 500,
  "duration_minutes": 180,
  "download_limit_mb": 1500,
  "upload_limit_mb": 300,
  "is_active": true
}
```

**Réponse 201 :** objet plan créé.

**Erreurs 400 :**
```json
{ "price_fcfa": ["Le prix doit être positif."] }
{ "duration_minutes": ["La durée doit être supérieure à zéro."] }
```

---

### `GET /api/v1/ticket-plans/{id}/`

Détail d'un plan. Mêmes champs que la liste.

---

### `PATCH /api/v1/ticket-plans/{id}/`

Mise à jour partielle. Envoyer uniquement les champs à modifier.

```json
{ "is_active": false }
```

> Désactiver un plan n'affecte pas les sessions déjà créées — leur référence `ticket_plan` est conservée en lecture.

---

### `DELETE /api/v1/ticket-plans/{id}/`

Supprime un plan. Les sessions existantes associées à ce plan voient leur champ `ticket_plan` passer à `null` (conservation de l'historique).

**Réponse 204 :** No content.

---

## 2. Historique des sessions — ConnectionSession

---

### `GET /api/v1/sessions/`

Historique paginé des sessions WiFi de l'owner connecté, triées par date décroissante.

**Filtres query string :**

| Paramètre   | Type    | Description                              | Exemple                    |
|-------------|---------|------------------------------------------|----------------------------|
| `is_active` | boolean | Sessions en cours ou terminées           | `?is_active=true`          |
| `client`    | int     | ID d'un OwnerClient                      | `?client=42`               |
| `date_from` | date    | Début de la fenêtre (inclusif)           | `?date_from=2026-04-01`    |
| `date_to`   | date    | Fin de la fenêtre (inclusif)             | `?date_to=2026-04-21`      |

**Réponse 200 :**
```json
{
  "count": 1240,
  "next": "https://app.wifileads.io/api/v1/sessions/?page=2",
  "previous": null,
  "results": [
    {
      "id": 587,
      "session_key": "f8e7d6c5-b4a3-2109-8765-4321fedcba98",
      "client": 42,
      "client_email": "client@example.com",
      "client_phone": "+22997123456",
      "plan_name": "Pass 1h",
      "plan_price_fcfa": 200,
      "mac_address": "AA:BB:CC:DD:EE:FF",
      "ip_address": "192.168.88.42",
      "ticket_id": "TKT-54321",
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
      "user_agent": "Mozilla/5.0 (Linux; Android 11; Tecno Spark 7)..."
    }
  ]
}
```

**Champs importants :**

| Champ             | Notes                                                                       |
|-------------------|-----------------------------------------------------------------------------|
| `is_active`       | Peut basculer à `false` automatiquement après 10 min sans heartbeat        |
| `ended_at`        | `null` si session encore active                                             |
| `duration_seconds`| Utilise `ended_at - started_at` si disponible, sinon `uptime_seconds`      |
| `plan_name`       | `null` si le plan n'a pas pu être détecté — affichez "Plan inconnu"        |
| `plan_price_fcfa` | `null` si plan inconnu — ne pas inclure dans le calcul de revenu           |
| `client_email`    | Peut être `null` si le client n'a fourni qu'un téléphone                   |

---

### `GET /api/v1/sessions/{id}/`

Détail d'une session. Mêmes champs que la liste.

---

## 3. Analytics sessions — SessionAnalyticsViewSet

Ces endpoints ne sont pas mis en cache côté backend. Pour le dashboard temps réel, faire un poll toutes les 30–60 secondes sur `overview/`.

---

### `GET /api/v1/session-analytics/overview/`

Vue d'ensemble KPIs pour le dashboard principal.

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

**Notes :**
- `active_sessions` = sessions avec `is_active=true` en ce moment.
- `avg_session_seconds` sur toutes les sessions de l'owner (pas uniquement aujourd'hui).
- Les revenus sont **estimés** : uniquement les sessions associées à un `TicketPlan`. Les sessions sans plan détecté ne contribuent pas.
- `estimated_revenue_today_fcfa` : somme des `price_fcfa` des tickets dont la session a démarré aujourd'hui.

---

### `GET /api/v1/session-analytics/by-day/`

Nombre de sessions créées par jour sur les N derniers jours. Utile pour un graphique en barres ou une courbe de tendance.

**Paramètres :**
- `?days=30` — nombre de jours (défaut : 30, max : 90)

**Réponse 200 :**
```json
{
  "labels": ["2026-03-22", "2026-03-23", "2026-03-24"],
  "data":   [38, 45, 52]
}
```

> `labels` et `data` sont parallèles et de même longueur.

---

### `GET /api/v1/session-analytics/by-hour/`

Répartition des sessions par heure de la journée (0–23). Utile pour identifier les heures de pointe et ajuster les prix.

**Réponse 200 :**
```json
{
  "labels": [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23],
  "data":   [3, 1, 0, 0, 0, 2, 8, 15, 18, 14, 12, 16, 21, 19, 14, 13, 17, 22, 35, 41, 38, 28, 18, 7]
}
```

> Toujours 24 buckets, même si certaines heures ont 0 session.

---

### `GET /api/v1/session-analytics/top-clients/`

Top 10 clients les plus actifs de l'owner, triés par nombre de sessions décroissant.

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
  },
  {
    "client_id": 17,
    "email": null,
    "phone": "+22996555444",
    "mac_address": "11:22:33:44:55:66",
    "sessions_count": 54,
    "total_seconds": 89100,
    "total_mb": 7821.2
  }
]
```

> `email` peut être `null`. Utilisez `phone` ou `mac_address` comme identifiant de repli pour l'affichage.

---

## 4. Codes HTTP

| Code | Signification                                  |
|------|------------------------------------------------|
| 200  | Succès (aussi retourné sur erreur heartbeat)   |
| 201  | Plan créé / session créée                      |
| 204  | Plan supprimé                                  |
| 400  | Erreur de validation                           |
| 401  | Non authentifié — token absent ou expiré       |
| 403  | Tentative d'accès cross-owner                  |
| 404  | Ressource introuvable                          |
| 429  | Rate limit dépassé (endpoints publics tracker) |

---

## 5. Détection automatique du plan

Le backend associe chaque session à un `TicketPlan` en comparant les limites MikroTik (`rx-limit` / `tx-limit`) aux valeurs `download_limit_mb` / `upload_limit_mb` des plans de l'owner.

**Règles à respecter côté configuration :**
- Les valeurs MikroTik et les plans WiFiLeads doivent être strictement identiques pour le matching.
- Exemple : MikroTik `rx-limit=10M` = 10 485 760 bytes → `download_limit_mb` du plan doit valoir `10` (pas `10.24`).
- Pour les plans illimités (MikroTik `---`), le fallback se fait sur la durée — moins précis.

**Conséquences pour le frontend :**
- Afficher un badge gris "Plan inconnu" si `plan_name` est `null` — ne pas ignorer ces sessions.
- Ne pas inclure les sessions sans plan dans les calculs de revenu.
- Suggérer à l'owner de créer ses plans dans WiFiLeads s'il a beaucoup de sessions sans plan détecté.

---

## 6. Gestion du statut `is_active`

Une session `is_active=true` peut basculer à `false` de deux façons :

1. **Logout explicite** : `tracker.js` envoie `POST /tracking/end/` depuis `logout.html` via `navigator.sendBeacon()`.
2. **Timeout automatique** : la tâche Celery `cleanup_stale_sessions` ferme les sessions sans heartbeat depuis > 10 minutes (toutes les 5 minutes).

**Pour le dashboard temps réel :**
- Poller `overview/` toutes les 30–60 s pour mettre à jour `active_sessions`.
- Poller `sessions/?is_active=true` pour la liste des sessions en cours.
- Ne pas mettre ces données en cache côté frontend — la fraîcheur est la valeur ajoutée.

---

## 7. Exemple d'intégration dashboard

### Bloc KPIs en temps réel

```typescript
// Polling toutes les 30s
const { data: overview } = useQuery({
  queryKey: ['session-analytics', 'overview'],
  queryFn: () => api.get('/session-analytics/overview/'),
  refetchInterval: 30_000,
})

// Affichage
<KPICard label="Sessions actives" value={overview.active_sessions} live />
<KPICard label="Aujourd'hui" value={overview.sessions_today} />
<KPICard label="Revenu estimé (mois)" value={`${overview.estimated_revenue_month_fcfa} FCFA`} />
```

### Graphique sessions par jour

```typescript
const { data: byDay } = useQuery({
  queryKey: ['session-analytics', 'by-day', { days: 30 }],
  queryFn: () => api.get('/session-analytics/by-day/?days=30'),
})

// Recharts
<LineChart data={byDay.labels.map((label, i) => ({ label, count: byDay.data[i] }))}>
  <XAxis dataKey="label" />
  <YAxis />
  <Line dataKey="count" />
</LineChart>
```

### Liste sessions avec filtre actives

```typescript
const { data: sessions } = useQuery({
  queryKey: ['sessions', { isActive: true }],
  queryFn: () => api.get('/sessions/?is_active=true'),
  refetchInterval: 30_000,
})
```

---

**Documentation mise à jour le 22/04/2026**
