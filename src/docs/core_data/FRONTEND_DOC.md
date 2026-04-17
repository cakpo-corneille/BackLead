# WiFi Marketing Platform - Documentation Frontend

**Version :** 3.0
**Date :** Avril 2026
**Public :** Développeurs Frontend (Dashboard Owner)
**Base URL :** `https://VOTRE_DOMAINE/api/v1/`

---

## Authentification

**Header requis pour tous les endpoints dashboard :**
```
Authorization: Bearer <access_token>
```

---

## 1. Schéma de formulaire

### GET `/api/v1/schema/`

Récupérer le schéma du propriétaire connecté.

**Réponse 200 :**
```json
{
  "id": 1,
  "public_key": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "owner": 42,
  "name": "Mon Formulaire",
  "title": "Bienvenue !",
  "description": "Remplissez ce formulaire pour accéder au WiFi.",
  "logo": null,
  "button_label": "Accéder au WiFi",
  "schema": {
    "fields": [
      { "name": "nom",   "label": "Nom complet", "type": "text",  "required": true  },
      { "name": "email", "label": "Email",        "type": "email", "required": true  },
      { "name": "phone", "label": "Téléphone",    "type": "phone", "required": false }
    ]
  },
  "double_opt_enable": false,
  "enable": true,
  "version": 1,
  "created_at": "2026-01-15T10:30:00Z",
  "updated_at": "2026-04-17T14:22:00Z"
}
```

---

### PATCH `/api/v1/schema/`

Mettre à jour le schéma.

**Body (partiel) :**
```json
{
  "name": "Mon Nouveau Formulaire",
  "title": "Accès WiFi Gratuit",
  "description": "Quelques informations pour vous connecter.",
  "button_label": "Me connecter",
  "double_opt_enable": true,
  "schema": {
    "fields": [
      { "name": "nom",   "label": "Nom",   "type": "text",  "required": true  },
      { "name": "email", "label": "Email", "type": "email", "required": true  }
    ]
  }
}
```

**Réponse 200 :** Schéma complet mis à jour (version auto-incrémentée si `schema` ou `double_opt_enable` changent)

---

### GET `/api/v1/schema/{public_key}/public/`

Récupérer le schéma public pour affichage dans le widget (endpoint non authentifié).

---

## 2. Leads

### GET `/api/v1/leads/`

Liste paginée des leads du propriétaire connecté.

**Paramètres de filtrage :**
| Paramètre    | Type    | Description                              | Exemple               |
|--------------|---------|------------------------------------------|-----------------------|
| `is_verified`| boolean | Filtrer par statut de vérification       | `?is_verified=true`   |
| `search`     | string  | Recherche dans email, phone, payload     | `?search=koffi`       |
| `date_from`  | date    | Leads créés à partir de cette date       | `?date_from=2026-01-01`|
| `date_to`    | date    | Leads créés jusqu'à cette date           | `?date_to=2026-04-17` |
| `ordering`   | string  | Tri des résultats                        | `?ordering=-created_at`|
| `page`       | int     | Numéro de page                           | `?page=2`             |
| `page_size`  | int     | Résultats par page (max 100)             | `?page_size=50`       |

**Réponse 200 :**
```json
{
  "count": 347,
  "next": "https://VOTRE_DOMAINE/api/v1/leads/?page=2",
  "previous": null,
  "results": [
    {
      "id": 1,
      "mac_address": "AA:BB:CC:DD:EE:FF",
      "client_token": "f8e7d6c5-b4a3-2109-8765-4321fedcba98",
      "email": "client@example.com",
      "phone": "+22997123456",
      "payload": {
        "nom": "Koffi",
        "email": "client@example.com",
        "source": "Instagram"
      },
      "recognition_level": 25,
      "is_verified": true,
      "tags": ["VIP", "Fidèle"],
      "notes": "Client régulier du vendredi soir.",
      "created_at": "2026-03-15T18:42:00Z",
      "updated_at": "2026-04-10T09:15:00Z",
      "last_seen": "2026-04-10T09:15:00Z"
    }
  ]
}
```

---

### GET `/api/v1/leads/{id}/`

Détail d'un lead.

**Réponse 200 :** Objet lead complet (même format que ci-dessus)

---

### PATCH `/api/v1/leads/{id}/`

Modifier les tags et notes d'un lead.

**Body :**
```json
{
  "tags": ["VIP", "Fidèle"],
  "notes": "Préfère être contacté par WhatsApp."
}
```

**Réponse 200 :** Lead mis à jour

---

### DELETE `/api/v1/leads/{id}/`

Supprimer un lead.

**Réponse 204 :** Pas de contenu

---

### POST `/api/v1/leads/{id}/resend-verification/`

Renvoyer manuellement un code OTP à un client non vérifié.

Utile depuis le CRM quand le propriétaire veut relancer la vérification d'un client qui n'a pas complété le double opt-in.

**Réponse 200 :**
```json
{ "detail": "Code de vérification renvoyé avec succès." }
```

**Erreurs possibles :**
```json
{ "detail": "Ce client est déjà vérifié." }
{ "detail": "Token client manquant." }
```

---

### GET `/api/v1/leads/stats/`

Statistiques agrégées sur les leads.

**Réponse 200 :**
```json
{
  "total": 347,
  "verified": 89,
  "verification_rate": 25.6,
  "new_today": 12,
  "new_this_week": 47,
  "new_this_month": 183,
  "avg_recognition_level": 18.4
}
```

---

### GET `/api/v1/leads/export/`

Export CSV de tous les leads.

**Réponse 200 :** Fichier CSV (Content-Disposition: attachment)

```
Content-Type: text/csv; charset=utf-8
Content-Disposition: attachment; filename="leads_2026-04-17.csv"
```

---

## 3. Analytics

### GET `/api/v1/analytics/overview/`

Vue globale du tableau de bord.

**Réponse 200 :**
```json
{
  "total_leads": 347,
  "verified_leads": 89,
  "verification_rate": 25.6,
  "new_this_week": 47,
  "new_this_month": 183,
  "recognition_distribution": {
    "inconnu":  112,
    "visiteur":  98,
    "regulier":  87,
    "fidele":    50
  }
}
```

> **Cache :** Ces données sont mises en cache pendant 1 heure. Elles ne reflètent pas en temps réel les dernières soumissions.

---

### GET `/api/v1/analytics/leads-by-day/`

Courbe temporelle des leads.

**Paramètre :** `?days=30` (défaut : 30, max recommandé : 90)

**Réponse 200 :**
```json
{
  "labels": ["2026-03-18", "2026-03-19", "..."],
  "data":   [12, 8, 15, 3, 22, "..."]
}
```

---

### GET `/api/v1/analytics/recognition/`

Distribution des niveaux de fidélité.

**Réponse 200 :**
```json
{
  "inconnu":   112,
  "visiteur":   98,
  "regulier":   87,
  "fidele":     50,
  "thresholds": { "visiteur": 5, "regulier": 20, "fidele": 50 }
}
```

---

### GET `/api/v1/analytics/verification-rate/`

Taux de vérification double opt-in.

**Réponse 200 :**
```json
{
  "total":       347,
  "verified":     89,
  "unverified":  258,
  "rate":         25.6
}
```

---

## 4. Codes HTTP

| Code | Signification                               |
|------|---------------------------------------------|
| 200  | Succès                                      |
| 201  | Ressource créée                             |
| 204  | Suppression réussie                         |
| 400  | Erreur de validation / données incorrectes  |
| 401  | Non authentifié (token manquant ou expiré)  |
| 403  | Non autorisé (tentative d'accès cross-owner)|
| 404  | Ressource non trouvée                       |
| 500  | Erreur serveur                              |

---

## 5. Niveaux de fidélité (recognition_level)

| Valeur    | Label     | Seuil     |
|-----------|-----------|-----------|
| 0 – 4     | Inconnu   | —         |
| 5 – 19    | Visiteur  | ≥ 5       |
| 20 – 49   | Régulier  | ≥ 20      |
| 50+       | Fidèle    | ≥ 50      |

---

**Documentation mise à jour le 17/04/2026**
