# Tracking API — Documentation Frontend

**Version :** 3.0
**Date :** Mai 2026
**Public :** Développeurs frontend (Dashboard Owner)
**Base URL :** `https://VOTRE_DOMAINE/api/v1/`

---

## Authentification

Tous les endpoints du dashboard nécessitent un JWT dans le header :

```
Authorization: Bearer <access_token>
```

Les endpoints `/sessions/login/` et `/sessions/logout/` sont **publics** — ils sont appelés directement par le routeur MikroTik et ne nécessitent aucune authentification.

---

## 1. Plans tarifaires

Les plans tarifaires sont les forfaits WiFi que le gérant propose à ses clients (1h, 4h, journée, etc.). L'app les utilise pour identifier automatiquement le plan d'une session à partir de sa durée.

### Récupérer la liste des plans

**`GET /api/v1/ticket-plans/`**

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

### Créer un plan

**`POST /api/v1/ticket-plans/`**

```json
{
  "name": "Pass journée",
  "price_fcfa": 1000,
  "duration_minutes": 1440,
  "is_active": true
}
```

### Modifier un plan

**`PATCH /api/v1/ticket-plans/{id}/`** — mêmes champs que la création, tous optionnels.

> Modifier le prix d'un plan n'affecte pas l'historique. Chaque session conserve une copie du prix au moment de la connexion dans le champ `amount_fcfa`.

### Supprimer un plan

**`DELETE /api/v1/ticket-plans/{id}/`**

Les sessions historiques liées conservent leurs données — le champ `ticket_plan` passe simplement à `null`.

---

## 2. Sessions WiFi

Les sessions représentent les connexions WiFi des clients. Une session est créée automatiquement dès qu'un client se connecte au hotspot, et fermée quand il se déconnecte ou que son ticket expire.

### Récupérer l'historique

**`GET /api/v1/sessions/`**

La liste est paginée. Filtres disponibles :

| Paramètre   | Description                                      | Exemple                  |
|-------------|--------------------------------------------------|--------------------------|
| `is_active` | Sessions en cours (`true`) ou terminées (`false`) | `?is_active=true`        |
| `client`    | ID du client                                     | `?client=42`             |
| `date_from` | Sessions démarrées à partir de cette date        | `?date_from=2026-04-01`  |
| `date_to`   | Sessions démarrées jusqu'à cette date            | `?date_to=2026-04-25`    |

**Réponse 200 :**

```json
{
  "count": 1240,
  "next": "https://DOMAINE/api/v1/sessions/?page=2",
  "previous": null,
  "results": [
    {
      "id": 587,
      "session_key": "f8e7d6c5-b4a3-2109-8765-4321fedcba98",
      "client": 42,
      "client_email": "client@example.com",
      "client_phone": "+22997123456",
      "ticket_plan": 3,
      "plan_name": "Pass 4h",
      "plan_price_fcfa": 200,
      "plan_duration_minutes": 240,
      "amount_fcfa": 200,
      "mac_address": "AA:BB:CC:DD:EE:FF",
      "ip_address": "192.168.88.42",
      "mikrotik_session_id": "*1A2B",
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
      "status": "connecté"
    }
  ]
}
```

### Détail d'une session

**`GET /api/v1/sessions/{id}/`** — mêmes champs que la liste.

---

### Le champ `status`

Le champ `status` remplace les anciens `is_active` et `disconnect_cause`. Il peut prendre trois valeurs :

| Valeur | Signification |
|---|---|
| `"connecté"` | La session est en cours, le client est sur le réseau |
| `"déconnecté"` | Le client s'est déconnecté manuellement ou a été coupé |
| `"expiré"` | Le ticket a atteint sa durée maximale |

Pour l'affichage, un badge coloré suffit : vert pour `connecté`, gris pour `déconnecté`, orange pour `expiré`.

---

### Le champ `session_timeout_seconds`

C'est la durée totale accordée au ticket, fixée au moment de la connexion. Elle ne change jamais. Ça permet d'afficher à la fois la durée du ticket et le temps réellement consommé.

Correspondances utiles pour l'affichage :

```
3600   → "Ticket de 1h"
7200   → "Ticket de 2h"
14400  → "Ticket de 4h"
43200  → "Ticket de 12h"
86400  → "Ticket de 24h (1 jour)"
0      → "Durée non communiquée"
```

---

### Afficher le plan d'une session

Trois cas peuvent se présenter :

| Situation | Quoi afficher |
|---|---|
| `ticket_plan` est renseigné | Nom + prix + durée du plan |
| `ticket_plan` est null mais `session_timeout_seconds > 0` | Badge jaune "Plan non configuré" (la durée est connue mais aucun plan ne correspond exactement) |
| `ticket_plan` est null et `session_timeout_seconds = 0` | Badge gris "Plan inconnu" |

Le deuxième cas se produit quand le gérant n'a pas encore créé de plan dont la durée correspond exactement au ticket. Il suffit de créer le plan manquant pour que les prochaines sessions soient automatiquement identifiées.

---

### Le champ `amount_fcfa`

C'est le revenu réel généré par cette session — une copie figée du prix du plan au moment de la connexion. Utiliser ce champ pour les calculs financiers, pas `plan_price_fcfa` qui reflète le prix actuel du plan (qui a pu changer depuis).

---

## 3. Analytics sessions

### Vue d'ensemble — KPIs globaux

**`GET /api/v1/session-analytics/overview/`**

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

Les revenus sont calculés uniquement sur les sessions dont le plan a été identifié. Les sessions sans plan (`ticket_plan: null`) ne sont pas comptabilisées — c'est pourquoi ils sont qualifiés d'estimés.

Pour les KPIs temps réel du dashboard, faire un poll toutes les 30 à 60 secondes sur cet endpoint. Ne pas mettre en cache côté frontend.

---

### Sessions par jour

**`GET /api/v1/session-analytics/by-day/?days=30`**

Paramètre `days` : nombre de jours à inclure. Défaut 30, max 90.

```json
{
  "labels": ["2026-03-22", "2026-03-23", "2026-03-24"],
  "data":   [38, 45, 52]
}
```

---

### Heures de pointe

**`GET /api/v1/session-analytics/by-hour/`**

Retourne 24 buckets — un par heure de la journée. Utile pour identifier les moments de forte affluence.

```json
{
  "labels": [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23],
  "data":   [1, 0, 0, 0, 0, 0, 2, 8, 15, 22, 28, 35, 41, 38, 32, 28, 22, 30, 38, 41, 35, 22, 12, 4]
}
```

---

### Top clients

**`GET /api/v1/session-analytics/top-clients/`**

Les 10 clients les plus actifs en nombre de sessions.

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

## 4. Snippet d'intégration RouterOS

Chaque gérant dispose d'un snippet RouterOS généré automatiquement depuis son profil. Il contient deux scripts prêts à coller dans WinBox :

- `on_login` : à placer dans le champ "On Login" du profil hotspot
- `on_logout` : à placer dans le champ "On Logout" du profil hotspot

Ces scripts sont disponibles dans la réponse de `GET /api/v1/config/` (app `core_data`), dans le champ `tracking_snippet`.

---

## 5. Codes HTTP

| Code | Ce que ça signifie pour toi |
|------|-----------------------------|
| 200  | Tout s'est bien passé |
| 201  | Ressource créée (plan) |
| 204  | Ressource supprimée |
| 400  | Les données envoyées sont invalides — vérifier les messages d'erreur dans la réponse |
| 401  | Token JWT absent ou expiré — rediriger vers la page de connexion |
| 403  | L'utilisateur tente d'accéder aux données d'un autre gérant — ne devrait pas arriver en usage normal |
| 404  | Ressource introuvable |
| 429  | Trop de requêtes — appliquer un backoff exponentiel |

---

## 6. Conseils d'intégration

**Pour le tableau des sessions en temps réel** — filtrer sur `?is_active=true` et rafraîchir toutes les 30 à 60 secondes. Paginer avec `?page_size=50` pour ne pas charger tout l'historique.

**Pour l'historique long** — utiliser `date_from` et `date_to` pour limiter la fenêtre de données. Paginer avec `?page=2&page_size=50`.

**Pour les revenus** — toujours utiliser `amount_fcfa` (champ de la session) plutôt que `plan_price_fcfa` pour les calculs financiers. Le prix peut avoir changé depuis la session.

**Pour afficher la progression d'une session active** — `uptime_seconds` est la durée déjà consommée, `session_timeout_seconds` est la durée totale du ticket. La progression est donc `uptime_seconds / session_timeout_seconds * 100`.

---

**Documentation mise à jour le 02/05/2026**
