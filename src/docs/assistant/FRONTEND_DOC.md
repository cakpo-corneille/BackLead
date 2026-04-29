# Assistant API — Documentation Frontend

**Version :** 1.0
**Date :** Avril 2026
**Public :** Développeurs Frontend (Dashboard Owner)
**Base URL :** `https://VOTRE_DOMAINE/api/v1/assistant/`

---

## Authentification

Tous les endpoints nécessitent un JWT :

```
Authorization: Bearer <access_token>
```

Les conversations et leurs messages sont **isolés par owner** :
impossible de voir/modifier celles d'un autre compte.

---

## 1. Chat avec l'IA

### POST `/api/v1/assistant/chat/`

Envoie un message à l'assistant. Crée automatiquement une nouvelle
conversation si `conversation_id` est absent, sinon la poursuit.

**Body — nouveau thread :**
```json
{
  "message": "Comment je configure mon premier formulaire ?"
}
```

**Body — suite d'un thread existant :**
```json
{
  "message": "Et pour activer le double opt-in ?",
  "conversation_id": 17
}
```

**Réponse 200 :**
```json
{
  "conversation_id": 17,
  "public_id": "f8e7d6c5-b4a3-2109-8765-4321fedcba98",
  "reply": {
    "id": 142,
    "role": "model",
    "content": "Pour activer le double opt-in, allez dans Paramètres → ...",
    "created_at": "2026-04-21T15:30:00Z"
  }
}
```

**Erreurs possibles :**
```json
{ "message": ["Ce champ ne peut être vide."] }                     // 400
{ "detail": "Conversation introuvable." }                          // 404 (cross-owner ou inexistante)
```

> Si Gemini est indisponible, la réponse reste **200** et `reply.content`
> contient un message de repli ("Désolé, l'assistant est temporairement
> indisponible..."). Le message est tout de même persisté côté serveur
> pour conserver l'historique cohérent.

---

## 2. Générer un schéma de formulaire

### POST `/api/v1/assistant/generate-form/`

Demande à l'IA de produire un schéma JSON prêt à être enregistré dans
`/api/v1/schema/`.

**Body :**
```json
{
  "prompt": "Je tiens un cybercafé à Cotonou, je veux collecter le prénom, l'email et le type de visiteur (étudiant, pro, autre)."
}
```

**Réponse 200 :**
```json
{
  "title": "Bienvenue au cybercafé",
  "description": "Renseignez ces informations pour accéder au WiFi.",
  "button_label": "Me connecter",
  "fields": [
    { "name": "first_name", "label": "Prénom",  "type": "text",   "required": true  },
    { "name": "email",      "label": "Email",   "type": "email",  "required": true  },
    {
      "name": "visitor_type",
      "label": "Type de visiteur",
      "type": "choice",
      "required": false,
      "options": ["Étudiant", "Pro", "Autre"]
    }
  ]
}
```

> ⚠️ Cet endpoint **ne sauvegarde pas** automatiquement. Le frontend
> doit envoyer la réponse à `PATCH /api/v1/schema/` (voir
> `core_data/FRONTEND_DOC.md`) une fois validée par l'owner.

**Codes d'erreur :**
| Code | Cause                                                    |
|------|----------------------------------------------------------|
| 400  | Prompt trop court (<5) ou trop long (>2000)              |
| 401  | Non authentifié                                          |
| 422  | L'IA a renvoyé du contenu inutilisable (JSON cassé, aucun champ valide) |
| 503  | Gemini indisponible / quota dépassé                      |

**Exemple flux complet (UI suggérée) :**

1. L'owner décrit son besoin dans un textarea.
2. POST `/assistant/generate-form/`.
3. Affichez un **aperçu** du formulaire généré.
4. L'owner ajuste si besoin (ajout/suppression de champs).
5. PATCH `/api/v1/schema/` avec `{ "schema": { "fields": [...] }, "title": ..., ... }`.

---

## 3. Liste des conversations

### GET `/api/v1/assistant/conversations/`

Conversations de l'owner connecté, triées par `last_message_at` desc.

**Réponse 200 :**
```json
{
  "count": 4,
  "next": null,
  "previous": null,
  "results": [
    {
      "id": 17,
      "public_id": "f8e7d6c5-b4a3-2109-8765-4321fedcba98",
      "title": "Comment je configure mon premier formulaire ?",
      "created_at": "2026-04-21T15:00:00Z",
      "last_message_at": "2026-04-21T15:30:00Z",
      "messages_count": 6
    }
  ]
}
```

---

## 4. Détail d'une conversation

### GET `/api/v1/assistant/conversations/{id}/`

Conversation complète avec tous ses messages, dans l'ordre chronologique.

**Réponse 200 :**
```json
{
  "id": 17,
  "public_id": "f8e7d6c5-b4a3-2109-8765-4321fedcba98",
  "title": "Comment je configure mon premier formulaire ?",
  "created_at": "2026-04-21T15:00:00Z",
  "updated_at": "2026-04-21T15:30:00Z",
  "messages": [
    {
      "id": 140,
      "role": "user",
      "content": "Comment je configure mon premier formulaire ?",
      "created_at": "2026-04-21T15:00:00Z"
    },
    {
      "id": 141,
      "role": "model",
      "content": "Allez dans la section Formulaire de votre dashboard...",
      "created_at": "2026-04-21T15:00:03Z"
    }
  ]
}
```

**Erreur :** `404` si la conversation appartient à un autre owner.

---

## 5. Supprimer une conversation

### DELETE `/api/v1/assistant/conversations/{id}/`

Supprime la conversation et **tous ses messages** (cascade).

**Réponse 204 :** Pas de contenu.
**Erreur :** `404` si introuvable ou cross-owner.

---

## 6. Bonnes pratiques côté UI

### Indicateur de chargement

Les appels Gemini prennent typiquement **1 à 4 secondes**. Affichez
toujours un indicateur (typing dots, spinner) pendant `chat/` et
`generate-form/`.

### Streaming

L'API actuelle **ne streame pas** la réponse — vous recevez le texte
complet d'un coup. Pour une UX type ChatGPT, vous pouvez animer le
rendu côté client (effet machine à écrire) après réception.

### Historique local

Pour réduire les allers-retours, mettez en cache la liste des
conversations côté client (revalidation toutes les 30 s ou à chaque
nouveau message envoyé).

### Gestion du fallback IA

Si `reply.content` commence par "Désolé, l'assistant est temporairement
indisponible", vous pouvez afficher un bouton **"Réessayer"** qui
renvoie le même `message` avec le même `conversation_id`.

### Tronquer les longs messages dans la liste

Le champ `title` est limité à 100 caractères, mais affichez-en max
60-80 dans la sidebar pour rester lisible.

---

## 7. Codes HTTP

| Code | Signification                                       |
|------|-----------------------------------------------------|
| 200  | Succès                                              |
| 204  | Conversation supprimée                              |
| 400  | Validation (champ vide, trop long, etc.)            |
| 401  | Non authentifié                                     |
| 404  | Conversation introuvable / cross-owner              |
| 422  | Sortie IA inutilisable (uniquement `generate-form/`)|
| 503  | Service IA indisponible (uniquement `generate-form/`)|

---

**Documentation mise à jour le 21/04/2026**
