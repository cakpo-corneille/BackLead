# WiFi Marketing Platform - Documentation Widget Public

**Version :** 3.0
**Date :** Avril 2026
**Public :** Développeurs intégrant le widget dans un portail captif

---

## Vue d'ensemble

Le widget est une couche de collecte de données qui s'insère **avant** la redirection finale du portail captif. Il fonctionne en deux phases :

```
Client WiFi
    │
    ▼
[Portail Captif Existant]
    │ Injecte le widget
    ▼
[Widget de Collecte]
    │ Soumission du formulaire
    ▼
[Double Opt-in OTP] ──── optionnel si double_opt_enable=true
    │
    ▼
[Redirection Finale] ──→ Accès Internet accordé
```

---

## Récupération du schéma (public, sans auth)

### GET `/api/v1/schema/{public_key}/public/`

Récupère le schéma de formulaire configuré par le propriétaire.

**Paramètre :** `public_key` — UUID du propriétaire (fourni lors de l'intégration)

**Réponse 200 :**
```json
{
  "public_key": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "name": "Formulaire Café des Palmes",
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
  "version": 3
}
```

**Si le schéma est désactivé (`enable=false`) :**
```json
{ "detail": "Ce formulaire n'est pas disponible." }
```

---

## Soumission du formulaire

### POST `/api/v1/portal/submit/`

Soumet les données collectées par le widget.

**Body :**
```json
{
  "owner_id": 42,
  "mac_address": "AA:BB:CC:DD:EE:FF",
  "client_token": "f8e7d6c5-b4a3-2109-8765-4321fedcba98",
  "payload": {
    "nom": "Koffi Yves",
    "email": "koffi@example.com",
    "phone": "+22997123456",
    "source": "Instagram"
  }
}
```

**Champs :**
| Champ          | Type   | Requis | Description                                      |
|----------------|--------|--------|--------------------------------------------------|
| `owner_id`     | int    | Oui    | ID du propriétaire (fourni lors de l'intégration)|
| `mac_address`  | string | Non    | Adresse MAC du device (format `AA:BB:CC:DD:EE:FF`)|
| `client_token` | UUID   | Non    | Token client existant (si déjà connu)            |
| `payload`      | object | Oui    | Données du formulaire selon le schéma            |

**Réponse 200 — Client reconnu (pas de double opt-in) :**
```json
{
  "client_token": "f8e7d6c5-b4a3-2109-8765-4321fedcba98",
  "is_new": false,
  "double_opt_required": false,
  "redirect_url": "https://portail.wifi.exemple/succes?token=..."
}
```

**Réponse 200 — Nouveau client, double opt-in requis :**
```json
{
  "client_token": "nouveautoken-uuid-ici",
  "is_new": true,
  "double_opt_required": true,
  "redirect_url": null
}
```

**Erreurs possibles :**
```json
{ "detail": "Schéma introuvable ou inactif." }
{ "payload": { "email": ["Ce champ est requis."] } }
{ "mac_address": ["Format invalide. Exemple : AA:BB:CC:DD:EE:FF"] }
```

---

## Détection de client existant

L'API détecte automatiquement un client existant selon l'ordre de priorité suivant :

```
1. MAC address   ──→ si mac_address fourni et connu dans la base
2. Client token  ──→ si client_token fourni et connu
3. Téléphone     ──→ si phone présent dans le payload et connu
```

Si un client est reconnu :
- `is_new = false`
- `recognition_level` incrémenté
- `last_seen` mis à jour
- Redirection immédiate (pas de double opt-in si déjà vérifié)

---

## Double Opt-in (OTP)

Activé si `double_opt_enable = true` dans le schéma ET que le client fournit un email ou téléphone.

### Envoyer le code de vérification

### POST `/api/v1/portal/verify/` (étape envoi)

> Ce flux est déclenché automatiquement après `submit/` si `double_opt_required=true`.
> Le widget doit présenter un formulaire de saisie du code.

### Vérifier le code OTP

### POST `/api/v1/portal/verify/`

**Code OTP valable 5 minutes.**

**Body :**
```json
{
  "client_token": "nouveautoken-uuid-ici",
  "code": "847291",
  "channel": "email"
}
```

**Champs :**
| Champ          | Type   | Requis | Description                     |
|----------------|--------|--------|---------------------------------|
| `client_token` | UUID   | Oui    | Token obtenu lors du submit     |
| `code`         | string | Oui    | Code OTP reçu par email ou SMS  |
| `channel`      | string | Oui    | `"email"` ou `"sms"`           |

**Réponse 200 :**
```json
{
  "message": "Vérification réussie.",
  "is_verified": true,
  "redirect_url": "https://portail.wifi.exemple/succes?token=..."
}
```

**Erreurs possibles :**
```json
{ "detail": "Code expiré ou invalide." }
{ "detail": "Code incorrect. Veuillez réessayer." }
```

---

### Renvoyer le code OTP

### POST `/api/v1/portal/resend-verification/`

**Body :**
```json
{
  "client_token": "nouveautoken-uuid-ici",
  "channel": "email"
}
```

**Réponse 200 :**
```json
{ "message": "Code renvoyé avec succès." }
```

---

### Statut d'un client

### GET `/api/v1/portal/status/?token={client_token}`

Vérifier le statut d'un client sans passer par le submit.

**Réponse 200 :**
```json
{
  "client_token": "f8e7d6c5-b4a3-2109-8765-4321fedcba98",
  "is_verified": true,
  "recognition_level": 25,
  "is_new": false,
  "redirect_url": "https://portail.wifi.exemple/succes?token=..."
}
```

---

## Types de champs supportés

| Type       | Description                                     | Rendu suggéré                        |
|------------|-------------------------------------------------|--------------------------------------|
| `text`     | Texte libre                                     | `<input type="text">`                |
| `email`    | Adresse email (validation format)               | `<input type="email">`               |
| `phone`    | Numéro de téléphone                             | `<input type="tel">`                 |
| `choice`   | Liste de choix exclusifs                        | `<select>` ou radio buttons          |
| `checkbox` | Case à cocher (booléen)                         | `<input type="checkbox">`            |
| `date`     | Date                                            | `<input type="date">`                |
| `textarea` | Texte long                                      | `<textarea>`                         |

---

## TTLs (délais d'expiration)

| Événement                          | TTL      |
|------------------------------------|----------|
| Code OTP double opt-in             | 300 s (5 min) |
| Code OTP inscription / reset email | 600 s (10 min)|
| Rate limit renvoi code             | 60 s     |

---

## Intégration — Exemple de flux complet

```javascript
const PUBLIC_KEY = 'a1b2c3d4-e5f6-7890-abcd-ef1234567890';
const OWNER_ID = 42;
const API_BASE = 'https://VOTRE_DOMAINE/api/v1';

// Étape 1 : Charger le schéma
const schema = await fetch(`${API_BASE}/schema/${PUBLIC_KEY}/public/`).then(r => r.json());

// Rendre le formulaire selon schema.schema.fields

// Étape 2 : Soumettre le formulaire
const submitResult = await fetch(`${API_BASE}/portal/submit/`, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    owner_id: OWNER_ID,
    mac_address: getMacAddress(),        // depuis le portail captif
    client_token: getStoredToken(),      // depuis localStorage si connu
    payload: collectFormData(),
  })
}).then(r => r.json());

if (!submitResult.double_opt_required) {
  // Redirection directe
  window.location.href = submitResult.redirect_url;
} else {
  // Afficher le formulaire de saisie du code OTP
  showOtpForm(submitResult.client_token);
}

// Étape 3 : Vérifier le code OTP
const verifyResult = await fetch(`${API_BASE}/portal/verify/`, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    client_token: submitResult.client_token,
    code: userEnteredCode,
    channel: 'email',
  })
}).then(r => r.json());

if (verifyResult.is_verified) {
  window.location.href = verifyResult.redirect_url;
}
```

---

## Recommandations d'intégration

- **Stocker le `client_token`** en localStorage pour le renvoyer lors des prochaines connexions → améliore la détection et le `recognition_level`.
- **Toujours envoyer la MAC address** si le portail captif la fournit → détection prioritaire.
- **Respecter le `version`** du schéma pour invalider le cache côté widget si le formulaire a changé.
- **Gérer le cas `enable=false`** : afficher un message d'accueil alternatif sans collecte de données.

---

**Documentation mise à jour le 17/04/2026**
