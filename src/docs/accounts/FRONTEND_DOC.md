# Accounts API - Documentation Frontend

**Version :** 5.0
**Date :** Avril 2026
**Public :** Développeurs Frontend (Dashboard Owner)
**Base URL :** `https://VOTRE_DOMAINE/api/v1/accounts/`

---

## Authentification

L'API utilise des **tokens JWT** (access + refresh).

**Headers requis pour les endpoints authentifiés :**
```
Authorization: Bearer <access_token>
```

**Durée de vie des tokens :**
- Access token : **24 heures**
- Refresh token : **7 jours** (rotation à chaque usage)

---

## 1. Inscription

### POST `/api/v1/accounts/auth/register/`

**Body :**
```json
{
  "email": "proprietaire@example.com",
  "password": "MonMotPasse1"
}
```

**Règles mot de passe :**
- 8 à 15 caractères
- Au moins 1 majuscule, 1 minuscule, 1 chiffre

**Réponse 201 :**
```json
{
  "message": "Compte créé avec succès. Vérifiez votre email.",
  "user_id": 42
}
```

**Erreurs possibles :**
```json
{ "email": ["Un compte avec cet email existe déjà."] }
{ "password": ["Le mot de passe doit contenir au moins une majuscule."] }
```

---

## 2. Vérification OTP

### POST `/api/v1/accounts/auth/verify/`

Code OTP envoyé par email, valable **10 minutes**.

**Body :**
```json
{
  "user_id": 42,
  "code": "482917"
}
```

**Réponse 200 :**
```json
{
  "message": "Email vérifié avec succès.",
  "access_token": "<access_jwt>",
  "refresh_token": "<refresh_jwt>",
  "user": {
    "id": 42,
    "email": "proprietaire@example.com",
    "is_verify": true
  }
}
```

**Erreurs possibles :**
```json
{ "detail": "Code expiré ou invalide. Demandez un nouveau code." }
{ "detail": "Code incorrect. Veuillez réessayer." }
```

---

## 3. Renvoyer le code OTP

### POST `/api/v1/accounts/auth/resend_code/`

**Rate limit : 1 demande / 60 secondes.**

**Body :**
```json
{ "user_id": 42 }
```

**Réponse 200 :**
```json
{ "message": "Code de vérification renvoyé avec succès." }
```

**Erreur rate limit (429) :**
```json
{ "detail": "Merci d'attendre 60 secondes avant de renvoyer un code." }
```

---

## 4. Connexion

### POST `/api/v1/accounts/auth/login/`

**Body :**
```json
{
  "email": "proprietaire@example.com",
  "password": "MonMotPasse1"
}
```

**Réponse 200 :**
```json
{
  "access_token": "<access_jwt>",
  "refresh_token": "<refresh_jwt>",
  "user": {
    "id": 42,
    "email": "proprietaire@example.com",
    "is_verify": true
  }
}
```

**Erreurs possibles :**
```json
{ "detail": "Identifiants incorrects." }
{ "detail": "Compte non vérifié. Vérifiez votre email." }
```

---

## 5. Mot de passe oublié

### POST `/api/v1/accounts/auth/forgot_password/`

**Body :**
```json
{ "email": "proprietaire@example.com" }
```

**Réponse 200 :** (identique même si email inexistant — sécurité anti-énumération)
```json
{ "message": "Si cet email existe, un code de réinitialisation a été envoyé." }
```

---

## 6. Réinitialiser le mot de passe

### POST `/api/v1/accounts/auth/reset_password/`

**Body :**
```json
{
  "user_id": 42,
  "code": "193847",
  "new_password": "NouveauMdp1"
}
```

**Réponse 200 :**
```json
{ "message": "Mot de passe réinitialisé avec succès." }
```

---

## 7. Déconnexion

### POST `/api/v1/accounts/auth/logout/`

**Headers :** `Authorization: Bearer <access_token>`

**Body :**
```json
{ "refresh_token": "<refresh_jwt>" }
```

**Réponse 200 :**
```json
{ "message": "Déconnexion réussie." }
```

> **Note :** JWT étant stateless, la déconnexion est symbolique côté serveur. La sécurité réelle passe par la rotation des tokens et leur expiration.

---

## 8. Mon profil

### GET `/api/v1/accounts/profile/me/`

**Headers :** `Authorization: Bearer <access_token>`

**Réponse 200 :**
```json
{
  "user": { "id": 42, "email": "proprietaire@example.com", "is_verify": true },
  "business_name": "Café des Palmes",
  "logo": "logos/profile/cafe_des_palmes_logo.png",
  "logo_url": "https://VOTRE_DOMAINE/media/logos/profile/cafe_des_palmes_logo.png",
  "nom": "Koffi",
  "prenom": "Yves",
  "phone_contact": "+22997123456",
  "whatsapp_contact": "+22997123456",
  "pays": "Bénin",
  "ville": "Cotonou",
  "quartier": "Akpakpa",
  "main_goal": "collect_leads",
  "pass_onboarding": true,
  "is_complete": true
}
```

---

## 9. Mettre à jour le profil

### PATCH `/api/v1/accounts/profile/me/`

**Content-Type :** `multipart/form-data` (si upload logo) ou `application/json`

**Body (partiel) :**
```
business_name: Café des Palmes
nom: Koffi
prenom: Yves
phone_contact: +22997123456
whatsapp_contact: +22997123456
pays: Bénin
ville: Cotonou
quartier: Akpakpa
main_goal: collect_leads
logo: [fichier image JPEG/PNG/WebP, max 2MB]
```

**Réponse 200 :**
```json
{
  "message": "Profil mis à jour avec succès.",
  "profile": { "...profil complet..." }
}
```

**Erreurs logo :**
```json
{ "logo": ["Le logo ne doit pas dépasser 2 MB."] }
{ "logo": ["Format non autorisé. Utilisez JPEG, PNG ou WebP."] }
```

**Valeurs valides pour `main_goal` :**
| Valeur | Description |
|---|---|
| `"collect_leads"` | Collecter des leads |
| `"analytics"` | Analyser le trafic |
| `"marketing"` | Marketing ciblé |

---

## 10. Statut de complétion

### GET `/api/v1/accounts/profile/status/`

**Headers :** `Authorization: Bearer <access_token>`

**Réponse 200 :**
```json
{
  "pass_onboarding": true,
  "is_complete": false,
  "completion_percentage": 75,
  "missing_fields": ["prenom", "whatsapp_contact"],
  "has_business_name": true,
  "has_logo": true,
  "has_main_goal": true,
  "has_contact": true,
  "has_location": true
}
```

---

## 11. Changer le mot de passe

### POST `/api/v1/accounts/profile/change_password/`

**Headers :** `Authorization: Bearer <access_token>`

**Body :**
```json
{
  "old_password": "AncienMdp1",
  "new_password": "NouveauMdp1"
}
```

**Réponse 200 :**
```json
{ "message": "Mot de passe modifié avec succès." }
```

**Erreurs possibles :**
```json
{ "detail": "Mot de passe actuel incorrect." }
{ "new_password": ["Le mot de passe doit contenir au moins une majuscule."] }
```

---

## 12. Changer l'adresse email

### POST `/api/v1/accounts/profile/change_email/`

**Headers :** `Authorization: Bearer <access_token>`

**Étape 1 — Initier le changement**

Envoi d'un code OTP au **nouvel** email pour confirmation.

**Body :**
```json
{ "new_email": "nouvel.email@example.com" }
```

**Réponse 200 :**
```json
{
  "message": "Code de vérification envoyé à nouvel.email@example.com.",
  "user_id": 42
}
```

**Étape 2 — Confirmer le changement**

Utiliser l'endpoint `verify/` avec le `user_id` et le code reçu au **nouvel** email.

**Body :**
```json
{
  "user_id": 42,
  "code": "738291"
}
```

**Réponse 200 :**
```json
{ "message": "Email modifié avec succès." }
```

**Erreurs possibles :**
```json
{ "new_email": ["Un compte avec cet email existe déjà."] }
```

---

## Flux de navigation recommandé

```
Inscription → Vérification OTP → Login → Onboarding profil → Dashboard
     │                                           │
     └── Renvoyer code (si délai > 10 min) ──────┘
```

---

## Gestion des erreurs

### Structure d'erreur standard

```json
{ "detail": "Message d'erreur lisible par l'humain." }
```

### Erreurs de validation (champs)

```json
{
  "email": ["Un compte avec cet email existe déjà."],
  "password": ["Le mot de passe doit contenir au moins une majuscule."]
}
```

---

## Codes HTTP

| Code | Signification                               |
|------|---------------------------------------------|
| 200  | Succès                                      |
| 201  | Ressource créée                             |
| 400  | Erreur de validation / données incorrectes  |
| 401  | Non authentifié (token manquant ou expiré)  |
| 403  | Non autorisé                                |
| 404  | Ressource non trouvée                       |
| 429  | Trop de requêtes (rate limiting)            |
| 500  | Erreur serveur                              |

---

**Documentation mise à jour le 17/04/2026**
