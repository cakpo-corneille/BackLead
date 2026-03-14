# Accounts API - Documentation Frontend

**Version :** 4.0  
**Date :** Février 2026

---

## Vue d'ensemble

API REST pour authentification JWT + vérification email OTP + onboarding progressif.

**Base URL :** `/api/v1/accounts/`

---

## Flux utilisateur

### Inscription → Vérification → Onboarding → Dashboard

```
1. POST /auth/register/ (email + password)
   → user_id retourné + email OTP envoyé

2. POST /auth/verify/ (user_id + code)
   → tokens JWT + profile_status
   
3. Si profile_status.pass_onboading = false
   → PATCH /profile/me/ (remplir profil minimal)
   → redirect: /onboarding
   
4. Si profile_status.is_complete = true
   → redirect: /dashboard
```

### Connexion

```
1. POST /auth/login/ (email + password)
   
2. Si is_verify = false
   → 403 + redirect: /verify-email
   
3. Si pass_onboading = false
   → redirect: /onboarding
   
4. Sinon
   → redirect: /dashboard
```

### Reset mot de passe

```
1. POST /auth/forgot_password/ (email)
   → user_id + code OTP envoyé

2. POST /auth/reset_password/ (user_id + code + new_password)
   → mot de passe réinitialisé
```

---

## Endpoints

### 1. Inscription

**POST** `/api/v1/accounts/auth/register/`

```json
// Request
{
  "email": "owner@example.com",
  "password": "MyPass123"
}

// Response 201
{
  "ok": true,
  "message": "Compte créé. Un code de vérification a été envoyé.",
  "user_id": 42,
  "email": "owner@example.com"
}
```

**Validation password :** 8-15 car., 1 maj + 1 min + 1 chiffre

**Erreurs :** 400 (email déjà utilisé ou password invalide), 500 (erreur email)

---

### 2. Vérification Email

**POST** `/api/v1/accounts/auth/verify/`

```json
// Request
{
  "user_id": 42,
  "code": "123456"
}

// Response 200
{
  "ok": true,
  "access": "eyJ0eXAi...",
  "refresh": "eyJ0eXAi...",
  "user": {
    "id": 42,
    "email": "owner@example.com",
    "is_verify": true
  },
  "profile_status": {
    "pass_onboading": false,
    "is_complete": false,
    "missing_fields": ["business_name", "logo", "nom", "main_goal", "pays", "ville", "quartier"],
    "completion_percentage": 0,
    "has_business_name": false,
    "has_logo": false,
    "has_main_goal": false,
    "has_contact": false,
    "has_location": false
  },
  "redirect": "/onboarding"
}
```

**Erreurs :** 400 (code incorrect/expiré), 404 (user introuvable)

---

### 3. Renvoyer code

**POST** `/api/v1/accounts/auth/resend_code/`

```json
// Request
{ "user_id": 42 }

// Response 200
{ "ok": true, "message": "Nouveau code envoyé." }
```

**Erreurs :** 429 (rate limit 1/min), 404

---

### 4. Connexion

**POST** `/api/v1/accounts/auth/login/`

```json
// Request
{
  "email": "owner@example.com",
  "password": "MyPass123"
}

// Response 200
{
  "ok": true,
  "access": "eyJ0eXAi...",
  "refresh": "eyJ0eXAi...",
  "user": {
    "id": 42,
    "email": "owner@example.com",
    "is_verify": true
  },
  "profile_status": {
    "pass_onboading": true,
    "is_complete": true,
    "completion_percentage": 100
  },
  "redirect": "/dashboard"
}

// Response 403 (email non vérifié)
{
  "ok": false,
  "error": "Email non vérifié.",
  "redirect": "/verify-email",
  "user_id": 42
}
```

**Erreurs :** 400 (identifiants incorrects), 403 (email non vérifié)

---

### 5. Mot de passe oublié

**POST** `/api/v1/accounts/auth/forgot_password/`

```json
// Request
{ "email": "owner@example.com" }

// Response 200
{
  "ok": true,
  "message": "Code envoyé.",
  "user_id": 42
}
```

**Erreurs :** 404 (email inconnu)

---

### 6. Réinitialiser mot de passe

**POST** `/api/v1/accounts/auth/reset_password/`

```json
// Request
{
  "user_id": 42,
  "code": "123456",
  "new_password": "NewPass456"
}

// Response 200
{ "ok": true, "message": "Mot de passe réinitialisé." }
```

**Erreurs :** 400 (code invalide/expiré ou password invalide)

---

### 7. Récupérer profil

**GET** `/api/v1/accounts/profile/me/`

**Headers :** `Authorization: Bearer <access_token>`

```json
// Response 200
{
  "user": {
    "id": 42,
    "email": "owner@example.com",
    "is_verify": true
  },
  "profile": {
    "business_name": "Café des Palmes",
    "logo": "/media/logos/cafe.png",
    "logo_url": "https://api.com/media/logos/cafe.png",
    "nom": "Koffi",
    "prenom": "Yves",
    "phone_contact": "+22997123456",
    "whatsapp_contact": "+22997123456",
    "pays": "Bénin",
    "ville": "Cotonou",
    "quartier": "Akpakpa",
    "main_goal": "collect_leads",
    "is_complete": true
  },
  "profile_status": {
    "pass_onboading": true,
    "is_complete": true,
    "missing_fields": [],
    "completion_percentage": 100
  }
}
```

---

### 8. Mettre à jour profil

**PATCH** `/api/v1/accounts/profile/me/`

**Headers :** `Authorization: Bearer <access_token>`

**JSON :**
```json
{
  "business_name": "Café des Palmes",
  "nom": "Koffi",
  "pays": "Bénin",
  "ville": "Cotonou",
  "quartier": "Akpakpa",
  "main_goal": "collect_leads"
}
```

**FormData (avec logo) :**
```javascript
const formData = new FormData();
formData.append('business_name', 'Café des Palmes');
formData.append('logo', fileInput.files[0]);
formData.append('nom', 'Koffi');
```

```json
// Response 200
{
  "ok": true,
  "profile": { /* ... */ },
  "profile_status": {
    "pass_onboading": true,
    "is_complete": false,
    "completion_percentage": 85
  },
  "redirect": "/onboarding"  // ou "/dashboard" si is_complete=true
}
```

---

### 9. Statut profil

**GET** `/api/v1/accounts/profile/status/`

```json
// Response 200
{
  "pass_onboading": false,
  "is_complete": false,
  "missing_fields": ["logo", "main_goal"],
  "completion_percentage": 71,
  "has_business_name": true,
  "has_logo": false,
  "has_main_goal": false,
  "has_contact": true,
  "has_location": true
}
```

---

### 10. Changer mot de passe

**POST** `/api/v1/accounts/profile/change_password/`

**Headers :** `Authorization: Bearer <access_token>`

```json
// Request
{
  "old_password": "OldPass123",
  "new_password": "NewPass456"
}

// Response 200
{ "ok": true, "message": "Mot de passe modifié." }
```

**Erreurs :** 400 (ancien mdp incorrect ou nouveau invalide)

---

## Types TypeScript

```typescript
interface User {
  id: number;
  email: string;
  is_verify: boolean;
}

interface OwnerProfile {
  business_name: string;
  logo: string;
  logo_url: string;
  nom: string;
  prenom: string;
  phone_contact: string;
  whatsapp_contact: string;
  pays: string;
  ville: string;
  quartier: string;
  main_goal: 'collect_leads' | 'analytics' | 'marketing';
  is_complete: boolean;  // READ-ONLY
}

interface ProfileStatus {
  pass_onboading: boolean;        // Champs minimaux OK
  is_complete: boolean;           // Profil 100% complet
  missing_fields: string[];
  completion_percentage: number;
  has_business_name: boolean;
  has_logo: boolean;
  has_main_goal: boolean;
  has_contact: boolean;
  has_location: boolean;
}
```

---

## Champs obligatoires

### pass_onboading = true

- `business_name` ≠ `WIFI-ZONE {user.id}`
- `logo` ≠ `logos/default.png`
- `nom` non vide
- `phone_contact` OU `whatsapp_contact`
- `pays`, `ville`, `quartier` non vides
- `main_goal` défini

### is_complete = true

`pass_onboading = true` + `prenom` + `phone_contact` ET `whatsapp_contact`

---

## JWT Tokens

### Stockage

```javascript
localStorage.setItem('access_token', response.access);
localStorage.setItem('refresh_token', response.refresh);
```

### Utilisation

```javascript
headers: {
  'Authorization': `Bearer ${localStorage.getItem('access_token')}`
}
```

### Refresh

```javascript
POST /api/token/refresh/
Body: { "refresh": "<refresh_token>" }
Response: { "access": "<new_access_token>" }
```

---

## Gestion erreurs

| Code | Signification |
|------|---------------|
| 200 | Succès |
| 201 | Créé |
| 400 | Données invalides |
| 401 | Non authentifié |
| 403 | Accès refusé |
| 404 | Introuvable |
| 429 | Rate limit |
| 500 | Erreur serveur |

---

## Rate Limiting

| Endpoint | Limite |
|----------|--------|
| `/auth/resend_code/` | 1/minute |

---

## Validation frontend (recommandée)

```javascript
function validatePassword(password) {
  if (password.length < 8 || password.length > 15) 
    return "8-15 caractères requis";
  if (!/[A-Z]/.test(password)) 
    return "Au moins une majuscule";
  if (!/[a-z]/.test(password)) 
    return "Au moins une minuscule";
  if (!/[0-9]/.test(password)) 
    return "Au moins un chiffre";
  return null;
}

function validateEmail(email) {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email);
}
```

---

**Documentation générée le 05/02/2026**
