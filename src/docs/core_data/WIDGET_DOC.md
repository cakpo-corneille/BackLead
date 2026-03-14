# WiFi Marketing Platform - Documentation Widget Public

**Version:** 2.0  
**Date:** Février 2026  
**Public:** Développeurs intégrant le widget dans un portail captif

---

## Table des matières

1. [Vue d'ensemble](#vue-densemble)
2. [Intégration technique](#intégration-technique)
3. [Flux utilisateur complet](#flux-utilisateur-complet)
4. [Endpoints API publics](#endpoints-api-publics)
5. [Validation et erreurs](#validation-et-erreurs)
6. [Double opt-in](#double-opt-in)
7. [Reconnaissance client](#reconnaissance-client)
8. [Gestion des conflits](#gestion-des-conflits)
9. [Rate limiting](#rate-limiting)

---

## Vue d'ensemble

### Contexte
Le widget permet de collecter les données des visiteurs WiFi via un formulaire généré dynamiquement selon la configuration du propriétaire (owner). Il communique avec le backend via 5 endpoints publics non authentifiés.

### Principes de fonctionnement
- **Configuration dynamique** : Le formulaire s'adapte au schéma défini par l'owner
- **Reconnaissance automatique** : Détection des visiteurs connus (MAC address ou token)
- **Validation stricte** : Email et téléphone vérifiés côté backend avant stockage
- **Double opt-in optionnel** : Vérification par code 6 chiffres (email ou SMS)
- **Anti-duplicate** : Détection intelligente par MAC, email ou téléphone
- **Persistance cross-device** : Token client pour reconnaissance multi-appareils

### Architecture de communication
```
Routeur WiFi → Widget JavaScript → API Backend → Base de données
```

**Données échangées :**
- MAC address (fournie par le routeur)
- Payload utilisateur (nom, email, téléphone, champs custom)
- Client token (généré backend, stocké côté client)
- Public key (identifie l'owner)

---

## Intégration technique

### Script d'intégration
Le propriétaire reçoit un snippet HTML contenant :
- URL du script widget
- Public key unique (UUID v4)

Le script se charge de :
1. Récupérer la configuration du formulaire
2. Détecter si le visiteur est connu
3. Afficher le formulaire ou rediriger
4. Gérer la soumission et la vérification

### Données requises du routeur
Le portail captif doit fournir au widget :
- **MAC address** du client (obligatoire)
- **URL de redirection** après validation (optionnel)

### Stockage local
Le widget utilise `localStorage` pour :
- **Client token** : Reconnaissance cross-device
- **Préférences** : Langue, consentement cookies

**Important :** Le token n'expire jamais côté client (géré backend).

---

## Flux utilisateur complet

### 1. Première visite (visiteur inconnu)

**Étape 1 : Provision**
- Widget appelle `/provision/` avec `public_key`
- Backend retourne schéma du formulaire + infos owner

**Étape 2 : Recognition**
- Widget appelle `/recognize/` avec `mac_address` + `client_token` (si existant)
- Backend retourne `recognized=false`

**Étape 3 : Affichage formulaire**
- Widget génère les champs selon le schéma
- Visiteur remplit et soumet

**Étape 4 : Submit**
- Widget appelle `/submit/` avec `payload` complet
- Backend valide, crée le lead, génère `client_token`
- Si double opt-in activé → envoie code 6 chiffres

**Étape 5a : Sans double opt-in**
- Backend retourne `created=true`
- Widget stocke `client_token`
- Le widget se retire pour laisser le portail captif continuer son flow normal.

**Étape 5b : Avec double opt-in**
- Backend retourne `requires_verification=true`
- Widget affiche input code 6 chiffres
- Visiteur saisit code
- Widget appelle `/confirm/`
- Backend valide → `is_verified=true`
- Le widget se retire pour laisser le portail captif continuer son flow normal.

---

### 2. Visite retour (visiteur connu)

**Étape 1 : Provision**
- Identique première visite

**Étape 2 : Recognition**
- Widget appelle `/recognize/` avec `mac_address` + `client_token`
- Backend trouve le lead, retourne `recognized=true`

**Étape 3a : Vérifié**
- Si `is_verified=true` → Le widget se retire pour laisser le portail captif continuer son flow normal.
- Pas d'affichage formulaire

**Étape 3b : Non vérifié**
- Backend retourne `is_verified=false`
- Widget affiche uniquement l'input code
- Flow de vérification identique première visite

---

### 3. Changement d'appareil (même personne, nouvelle MAC)

**Étape 1 & 2 : Provision + Recognition**
- MAC inconnue mais `client_token` existant
- Backend trouve via token, retourne `recognized=true, method='token'`

**Étape 3 : Mise à jour automatique**
- Backend incrémente `recognition_level`
- Pas de formulaire affiché
- Le widget se retire pour laisser le portail captif continuer son flow normal.

---

### 4. Conflit de contact (nouvelle MAC, email/phone existant)

**Cas :** Visiteur A utilise un nouvel appareil et saisit un email déjà enregistré sur un autre appareil.

**Étape 1-3 : Flow normal**
- Recognition retourne `recognized=false`
- Affichage formulaire

**Étape 4 : Submit avec conflit**
- Backend détecte email existant avec MAC différente
- Retourne `conflict_field='email'` + `requires_verification=true`
- Génère nouveau code pour l'email en conflit

**Étape 5 : Résolution**
- Widget affiche message : "Cet email existe déjà. Un code a été envoyé."
- Visiteur saisit code reçu
- Widget appelle `/submit/` avec `verification_code`
- Backend valide → fusionne les données sous un seul `client_token`
- Le widget se retire pour laisser le portail captif continuer son flow normal.

**Résultat :** Un seul lead avec plusieurs MAC addresses possibles.

---

## Endpoints API publics

**Base URL :** `https://api.votredomaine.com/api/v1/portal/`

**Aucun endpoint ne nécessite d'authentification.**

---

### 1. GET `/provision/`

**Rôle :** Récupérer la configuration du formulaire et les informations du propriétaire.

**Query Parameters :**
- `public_key` (requis) : UUID v4 identifiant l'owner

**Validations :**
- `public_key` manquant → 400
- `public_key` invalide ou inexistant → 404

**Réponse succès (200) :**
```json
{
  "schema": {
    "fields": [
      {
        "name": "nom",
        "label": "Nom complet",
        "type": "text",
        "required": true,
        "placeholder": "Jean Dupont"
      },
      {
        "name": "email",
        "label": "Email",
        "type": "email",
        "required": true
      },
      {
        "name": "phone",
        "label": "Téléphone",
        "type": "phone",
        "required": false,
        "placeholder": "+229 XX XX XX XX"
      }
    ]
  },
  "owner": {
    "business_name": "Café Central",
    "logo": "https://api.votredomaine.com/media/logos/cafe-central.png"
  },
  "double_opt_enable": true,
  "preferred_channel": "email"
}
```

**Champs schema.fields :**
- `name` : Identifiant unique du champ (clé dans le payload)
- `label` : Libellé affiché dans le formulaire
- `type` : Type de champ (voir section Types de champs)
- `required` : Booléen, champ obligatoire ou non
- `placeholder` : Texte indicatif (optionnel)
- `choices` : Array de valeurs (uniquement si `type='choice'`)

**Types de champs supportés :**
- `text` : Texte libre
- `email` : Email (validation stricte backend)
- `phone` : Téléphone (validation stricte backend)
- `number` : Nombre décimal
- `choice` : Sélection unique (radio ou select)
- `boolean` : Case à cocher

**Champ owner :**
- `business_name` : Nom de l'établissement
- `logo` : URL absolue du logo (ou logo par défaut)

**Champ double_opt_enable :**
- `true` : Vérification obligatoire avant accès internet
- `false` : Accès immédiat après soumission

**Champ preferred_channel :**
- `email` : Code envoyé par email
- `phone` : Code envoyé par SMS

**Erreurs possibles :**
- 400 : `{"error": "public_key query parameter is required"}`
- 404 : `{"error": "FormSchema with this public_key does not exist"}`

---

### 2. POST `/recognize/`

**Rôle :** Vérifier si le visiteur est déjà connu dans la base de données.

**Content-Type :** `application/json`

**Body :**
```json
{
  "public_key": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "mac_address": "AA:BB:CC:DD:EE:FF",
  "client_token": "f9e8d7c6-b5a4-3210-fedc-ba9876543210"
}
```

**Champs :**
- `public_key` (requis) : UUID de l'owner
- `mac_address` (requis) : Adresse MAC du client
- `client_token` (optionnel) : Token stocké côté client

**Validations :**
- `public_key` manquant ou invalide → 400
- `mac_address` manquant → 400

**Logique de reconnaissance :**
1. Recherche par `mac_address` (priorité haute)
2. Si non trouvé → recherche par `client_token`
3. Si aucun match → `recognized=false`

**Réponse visiteur connu (200) :**
```json
{
  "recognized": true,
  "is_verified": true,
  "client_token": "f9e8d7c6-b5a4-3210-fedc-ba9876543210",
  "method": "mac"
}
```

**Champs :**
- `recognized` : Booléen, visiteur trouvé
- `is_verified` : Booléen, a validé le double opt-in
- `client_token` : Token unique du visiteur
- `method` : Méthode de reconnaissance (`mac` ou `token`)

**Réponse visiteur inconnu (200) :**
```json
{
  "recognized": false,
  "is_verified": false,
  "client_token": null,
  "method": null
}
```

**Comportement attendu widget :**
- Si `recognized=true` et `is_verified=true` → le widget se retire.
- Si `recognized=true` et `is_verified=false` → afficher input code
- Si `recognized=false` → afficher formulaire complet

**Erreurs possibles :**
- 400 : `{"error": "public_key and mac_address are required"}`
- 404 : `{"error": "FormSchema not found"}`

---

### 3. POST `/submit/`

**Rôle :** Soumettre les données du visiteur et créer/mettre à jour le lead.

**Content-Type :** `application/json`

**Body minimal :**
```json
{
  "public_key": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "mac_address": "AA:BB:CC:DD:EE:FF",
  "payload": {
    "nom": "Jean Dupont",
    "email": "jean@example.com",
    "phone": "+22997123456"
  }
}
```

**Body avec token existant :**
```json
{
  "public_key": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "mac_address": "AA:BB:CC:DD:EE:FF",
  "client_token": "f9e8d7c6-b5a4-3210-fedc-ba9876543210",
  "payload": { ... }
}
```

**Body avec code de vérification (résolution conflit) :**
```json
{
  "public_key": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "mac_address": "AA:BB:CC:DD:EE:FF",
  "verification_code": "123456",
  "payload": { ... }
}
```

**Validations backend :**

**1. Validation structurelle :**
- `public_key` manquant → 400
- `mac_address` manquant → 400
- `payload` manquant ou vide → 400

**2. Validation contre le schéma :**
- Champs requis absents → 400
- Types invalides → 400
- Email invalide (syntaxe, domaine) → 400
- Téléphone invalide (format international) → 400

**3. Détection de duplicates :**
- Même `mac_address` → mise à jour
- Même `email` ou `phone` avec MAC différente → conflit

**Réponse succès sans double opt-in (201) :**
```json
{
  "created": true,
  "duplicate": false,
  "client_token": "f9e8d7c6-b5a4-3210-fedc-ba9876543210",
  "requires_verification": false
}
```

**Réponse succès avec double opt-in (201) :**
```json
{
  "created": true,
  "duplicate": false,
  "client_token": "f9e8d7c6-b5a4-3210-fedc-ba9876543210",
  "requires_verification": true,
  "message": "Un code de vérification a été envoyé à votre email."
}
```

**Réponse mise à jour (même MAC) (201) :**
```json
{
  "created": false,
  "duplicate": true,
  "client_token": "f9e8d7c6-b5a4-3210-fedc-ba9876543210",
  "requires_verification": false
}
```

**Réponse conflit de contact (200) :**
```json
{
  "conflict_field": "email",
  "message": "Cet email existe déjà. Un code de vérification a été envoyé.",
  "client_token": "f9e8d7c6-b5a4-3210-fedc-ba9876543210",
  "requires_verification": true
}
```

**Champs de réponse :**
- `created` : Booléen, nouveau lead ou mise à jour
- `duplicate` : Booléen, visiteur déjà existant
- `client_token` : Token unique à stocker
- `requires_verification` : Booléen, afficher input code
- `conflict_field` : Nom du champ en conflit (email ou phone)
- `message` : Message informatif pour l'utilisateur

**Erreurs possibles (400) :**
```json
{"error": "Le champ 'nom' est obligatoire."}
{"error": "Email invalide pour 'email': The domain name example.com does not exist"}
{"error": "Téléphone invalide pour 'phone': Format de téléphone invalide."}
{"error": "Le champ 'source' doit être l'une des options ['Facebook', 'Instagram']."}
{"error": "Schema must contain at least one field of type 'email' or 'phone'"}
```

---

### 4. POST `/confirm/`

**Rôle :** Valider le code de vérification et marquer le lead comme vérifié.

**Content-Type :** `application/json`

**Body :**
```json
{
  "client_token": "f9e8d7c6-b5a4-3210-fedc-ba9876543210",
  "code": "123456"
}
```

**Validations :**
- `client_token` manquant → 400
- `code` manquant → 400
- `code` format invalide (pas 6 chiffres) → 400
- Lead non trouvé → 404
- Code expiré (>120s) → 400
- Code incorrect → 400

**Réponse succès (200) :**
```json
{
  "ok": true,
  "message": "Vérification réussie. Le portail captif va maintenant vous donner accès."
}
```

**Comportement backend :**
1. Récupère le code depuis le cache Redis (`double_opt_{client_token}`)
2. Compare avec le code saisi
3. Si valide → `is_verified=True` + supprime le code du cache
4. Si invalide → retourne erreur

**Erreurs possibles :**
- 400 : `{"error": "client_token and code are required"}`
- 404 : `{"error": "Client not found"}`
- 400 : `{"error": "Code expiré ou invalide. Demandez un nouveau code."}`
- 400 : `{"error": "Code incorrect. Veuillez réessayer."}`

**Comportement attendu widget :**
- Succès → stocker `client_token` + le widget se retire.
- Échec code incorrect → permettre nouvelle saisie
- Échec code expiré → afficher bouton "Renvoyer le code"

---

### 5. POST `/resend/`

**Rôle :** Renvoyer un nouveau code de vérification (rate limited).

**Content-Type :** `application/json`

**Body :**
```json
{
  "client_token": "f9e8d7c6-b5a4-3210-fedc-ba9876543210"
}
```

**Validations :**
- `client_token` manquant → 400
- Lead non trouvé → 404
- Rate limit actif (60s) → 429

**Réponse succès (200) :**
```json
{
  "ok": true,
  "message": "Un nouveau code a été envoyé."
}
```

**Réponse rate limited (429) :**
```json
{
  "error": "Veuillez attendre 60 secondes avant de demander un nouveau code."
}
```

**Comportement backend :**
1. Vérifie rate limit via Redis (`resend_rate_limit_{client_token}`)
2. Génère nouveau code 6 chiffres
3. Stocke dans cache avec TTL 120s
4. Envoie via email ou SMS selon `preferred_channel`
5. Active rate limit 60s

**Comportement attendu widget :**
- Désactiver bouton "Renvoyer" pendant 60s après clic
- Afficher compte à rebours
- Message succès : "Code renvoyé avec succès"

**Erreurs possibles :**
- 400 : `{"error": "client_token is required"}`
- 404 : `{"error": "Client not found"}`
- 429 : `{"error": "Veuillez attendre 60 secondes..."}`

---

## Validation et erreurs

### Validation des emails

**Bibliothèque :** `email-validator`

**Règles :**
- Syntaxe RFC 5322 valide
- Domaine existant (vérification DNS désactivée en test)
- Normalisation automatique (lowercase)

**Exemples :**
- `Jean@EXAMPLE.COM` → normalisé en `jean@example.com`
- `invalid-email` → rejeté (400)
- `test@domaine-inexistant.xyz` → rejeté en prod (DNS check)

---

### Validation des téléphones

**Bibliothèque :** `phonenumbers`

**Règles :**
- Format international E164 ou national
- Numéro valide selon la région
- Normalisation automatique en E164

**Configuration :**
- `DEFAULT_PHONE_REGION=BJ` (Bénin par défaut)

**Exemples :**
- `97123456` → normalisé en `+22997123456` (Bénin)
- `+33612345678` → accepté tel quel
- `12345` → rejeté (trop court)

---

### Messages d'erreur standardisés

**Format général :**
```json
{
  "error": "Message d'erreur explicite"
}
```

**Ou pour détails multiples :**
```json
{
  "detail": "Message principal",
  "errors": {
    "email": ["Email invalide"],
    "phone": ["Téléphone invalide"]
  }
}
```

**Messages courants :**
- Champ manquant : `"Le champ 'nom' est obligatoire."`
- Type invalide : `"Le champ 'age' doit être un nombre."`
- Email invalide : `"Email invalide pour 'email': {raison}"`
- Phone invalide : `"Téléphone invalide pour 'phone': {raison}"`
- Choix invalide : `"Le champ 'source' doit être l'une des options [...]"`
- Code incorrect : `"Code incorrect. Veuillez réessayer."`
- Code expiré : `"Code expiré ou invalide. Demandez un nouveau code."`
- Rate limit : `"Veuillez attendre 60 secondes avant de..."`

---

## Double opt-in

### Activation
Configuré par l'owner dans `FormSchema.double_opt_enable`.

### Canaux supportés
- **Email :** Code envoyé via SMTP (Gmail, SendGrid, etc.)
- **SMS :** Code envoyé via provider (FasterMessage, Hub2, ou Console)

### Génération du code
- 6 chiffres numériques aléatoires (`secrets.choice`)
- Stocké dans Redis avec TTL 120 secondes
- Clé cache : `double_opt_{client_token}`

### Envoi asynchrone
- Celery worker traite l'envoi en background
- Fallback synchrone si Celery indisponible
- Retry automatique (max 3 tentatives)

### Expiration
- Code valide 2 minutes (120s)
- Après expiration → message "Code expiré"
- Visiteur doit cliquer "Renvoyer le code"

### Rate limiting
- 1 renvoi par minute maximum
- Clé cache : `resend_rate_limit_{client_token}`
- TTL 60 secondes

---

## Reconnaissance client

### Méthodes de reconnaissance

**1. Par MAC address (priorité haute)**
- Recherche dans `OwnerClient.mac_address`
- Identifie le device exact
- Incrémente `recognition_level` à chaque visite

**2. Par client token (priorité basse)**
- Recherche dans `OwnerClient.client_token`
- Permet reconnaissance cross-device
- Exemple : smartphone puis laptop

### Recognition level

**Définition :** Compteur de visites du client.

**Incrémentation :**
- +1 à chaque appel `/recognize/` où `recognized=true`
- +1 à chaque `/submit/` avec `duplicate=true`

**Utilisation :**
- Analytics dashboard : taux de retour
- Top clients : clients avec `recognition_level` élevé
- Fidélité : seuil calculé dynamiquement

**Calcul taux de retour :**
```
Returning clients = recognition_level > 2
Return rate = (returning clients / total clients) × 100
```

### Stockage du token

**Côté client (localStorage) :**
```javascript
localStorage.setItem('client_token', 'f9e8d7c6-...');
```

**Persistance :**
- Token ne change jamais pour un lead donné
- Survit à la suppression des cookies
- Partageable entre appareils (si même compte utilisateur)

---

## Gestion des conflits

### Définition d'un conflit
Un conflit survient lorsqu'un visiteur avec une **nouvelle MAC address** soumet un email ou téléphone **déjà existant** dans la base pour cet owner.

### Scénarios possibles

**1. Même device, nouvelles données**
- MAC identique → mise à jour automatique
- Pas de conflit

**2. Nouveau device, même personne**
- MAC différente, email existant
- Token différent ou absent
- → Conflit détecté

**3. Nouveau device, nouvelle personne (rare)**
- Deux personnes partagent un email
- → Conflit détecté (résolution via code)

### Flux de résolution

**Étape 1 : Détection**
- Backend compare `email` et `phone` du payload avec la base
- Si match avec MAC différente → conflit

**Étape 2 : Génération code**
- Code 6 chiffres envoyé à l'email/phone en conflit
- Message : "Cet email existe déjà. Un code a été envoyé."

**Étape 3 : Vérification**
- Visiteur saisit le code reçu
- Widget renvoie `/submit/` avec `verification_code`

**Étape 4 : Fusion**
- Backend valide le code
- Fusionne les données sous le `client_token` existant
- Nouvelle MAC ajoutée à la liste des devices du client

**Résultat :**
- Un seul lead dans la base
- Plusieurs MAC addresses possibles
- `recognition_level` incrémenté

### Champ `conflict_field`

**Valeurs possibles :**
- `email` : Email en conflit
- `phone` : Téléphone en conflit
- `null` : Aucun conflit

**Comportement widget :**
- Afficher message : "Cet {conflict_field} existe déjà..."
- Passer en mode vérification (input code uniquement)
- Masquer le reste du formulaire

---

## Rate limiting

### Endpoints concernés
- `/resend/` : 1 requête par minute par `client_token`

### Implémentation
- Cache Redis avec TTL
- Clé : `resend_rate_limit_{client_token}`
- Durée : 60 secondes

### Réponse rate limited
```json
HTTP 429 Too Many Requests
{
  "error": "Veuillez attendre 60 secondes avant de demander un nouveau code."
}
```

### Comportement attendu
- Widget désactive le bouton "Renvoyer"
- Affiche compte à rebours de 60 secondes
- Réactive après expiration

### Autres protections
- Les autres endpoints publics n'ont pas de rate limit explicite
- Protection générale via Nginx/Cloudflare en production

---

## Cas d'usage avancés

### 1. Visiteur sans email ni téléphone
Si le schéma ne contient aucun champ `email` ou `phone` avec `required=true`, la validation backend échoue.

**Règle :** Au moins un champ `email` OU `phone` doit être présent dans le schéma.

---

### 2. Formulaire à champs dynamiques
Le schéma peut changer à tout moment. Le widget doit rappeler `/provision/` à chaque nouvelle session pour obtenir la dernière version.

**Versioning :**
- Champ `FormSchema.version` incrémenté à chaque modification
- Widget peut comparer les versions pour détecter les changements

---

### 3. Multi-langue
Le widget gère la langue via `navigator.language` ou paramètre manuel.

**Textes affichés :**
- Messages d'erreur backend : français par défaut
- Labels formulaire : définis par l'owner dans le schéma
- Messages widget : gérés côté client

---

### 4. Offline / Erreur réseau
En cas d'échec réseau :
- Widget affiche message générique : "Erreur de connexion. Veuillez réessayer."
- Retry automatique après 3 secondes (optionnel)
- Ne pas stocker le `client_token` tant que la soumission n'a pas réussi

---

### 5. Rotation de clé publique
Si l'owner régénère sa `public_key` :
- L'ancienne clé devient invalide immédiatement
- Tous les appels avec l'ancienne clé retournent 404
- L'owner doit mettre à jour le snippet sur son routeur

**Aucune migration automatique** : c'est une action de sécurité volontaire.

---

## Récapitulatif des codes HTTP

| Code | Signification | Exemple |
|------|---------------|---------|
| 200 | Succès | Recognition, Confirm, Resend |
| 201 | Créé | Submit (nouveau lead) |
| 400 | Requête invalide | Validation échouée, champ manquant |
| 404 | Non trouvé | Public key invalide, client inexistant |
| 429 | Rate limit | Resend trop fréquent |
| 500 | Erreur serveur | Bug backend, DB down |

**Gestion erreurs recommandée :**
- 400 : Afficher le message d'erreur à l'utilisateur
- 404 : Contacter l'administrateur (clé invalide)
- 429 : Afficher compte à rebours
- 500 : Message générique "Service temporairement indisponible"

---

## Performances et optimisations

### Cache backend
- FormSchema mis en cache 1h par `public_key`
- Codes OTP en cache Redis (TTL 120s)
- Rate limits en cache Redis (TTL 60s)

### Latence attendue
- `/provision/` : <100ms
- `/recognize/` : <50ms
- `/submit/` : <200ms (avec validation)
- `/confirm/` : <50ms
- `/resend/` : <300ms (envoi async)

### Optimisation widget
- Appeler `/provision/` une seule fois au chargement
- Mettre en cache le schéma côté client (sessionStorage)
- Éviter les appels répétés à `/recognize/`

---

## Checklist d'intégration

**Avant déploiement, vérifier :**
- [ ] MAC address récupérée depuis le routeur
- [ ] Public key correcte dans le snippet
- [ ] Client token stocké dans localStorage après succès
- [ ] Gestion des 3 flux : nouveau visiteur, visiteur connu, conflit
- [ ] Affichage des erreurs de validation
- [ ] Désactivation bouton pendant soumission
- [ ] Compte à rebours 60s sur "Renvoyer le code"
- [ ] **Disparition du widget** après succès pour laisser le portail captif finaliser la connexion
- [ ] Gestion des erreurs réseau (retry ou message)
- [ ] Tests avec double opt-in activé ET désactivé
- [ ] Tests de conflits (même email, nouvelle MAC)

---

**Dernière mise à jour :** 09 Février 2026  
**Version API :** v1
