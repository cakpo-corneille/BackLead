# WiFiLeads — Notes projet

## Résumé du projet

API backend Django pour un **widget de collecte de leads** superposé à des portails captifs WiFi existants, principalement destiné au marché ouest-africain (Bénin, Togo en priorité).

- **Stack** : Django 5 + DRF, JWT (SimpleJWT), PostgreSQL/SQLite, Redis + Celery, Brevo/Anymail
- **Apps** : `accounts` (propriétaires + auth OTP) et `core_data` (FormSchema, OwnerClient/leads, analytics, portail public)
- **Documentation détaillée** : `src/docs/accounts/` et `src/docs/core_data/` (BACKEND_DOC, FRONTEND_DOC, WIDGET_DOC)

Pas de frontend dans ce repo — API uniquement, consommée par un dashboard propriétaire et par le widget embarqué dans les portails captifs.

---

## Positionnement marché

Double axe de vente :

1. **Conformité ARCEP** (surtout au Bénin, post-communiqué du 13 janvier 2026)
   - L'ARCEP impose l'identification des abonnés sur toute zone WiFi
   - Notre flux (formulaire + double opt-in OTP + traçabilité MAC/token/last_seen) répond directement à cette obligation
   - Évite aux exploitants des amendes de 1 à 10 M FCFA

2. **Marketing / fidélisation**
   - Tags, notes, export CSV, analytics, niveaux de fidélité
   - Campagnes SMS/WhatsApp vers les leads collectés (retour clients)

Marchés cibles :
- **Togo** : cadre réglementaire clair (régime déclaratif ARCEP Togo), association pro active → marché de démarrage
- **Bénin** : marché en formalisation, autorisations par commune via `e-services.arcep.bj`, fenêtre d'opportunité

---

## Tracking app — Statut

- Modèles : `TicketPlan`, `ConnectionSession` (avec `session_key`, `last_heartbeat`, `ticket_plan` FK).
- Services : `handle_heartbeat` (création/update + matching plan), `close_session`, `close_stale_sessions`.
- Tâche périodique Celery : `tracking.cleanup_stale_sessions` toutes les 5 min (`CELERY_BEAT_SCHEDULE` dans `config/base.py`).
- Endpoints publics : `/api/v1/tracking/heartbeat/`, `/api/v1/tracking/end/`.
- Endpoints owner authentifiés : `/api/v1/ticket-plans/`, `/api/v1/sessions/`, `/api/v1/session-analytics/{overview,by-day,by-hour,top-clients}/`.
- Admin : gestion complète plans (actions activer/désactiver) et sessions (force close + export CSV).
- Tests : **72 tests verts** couvrant parsers, modèles, services, tâche Celery et tous les endpoints.

## Assistant IA (Gemini) — Statut

- App `assistant` ajoutée à `INSTALLED_APPS`. Migration `0001_initial` appliquée.
- Intégration : API Google Gemini directe via le SDK `google-genai`. Clé à fournir dans `.env` sous `GEMINI_API_KEY` (obtenue sur https://aistudio.google.com/apikey).
- Modèles : `ChatConversation`, `ChatMessage` (historique persisté par owner).
- Modèle Gemini par défaut : `gemini-2.5-flash` (max 8192 tokens).
- Endpoints :
  - `POST /api/v1/assistant/chat/` — agent conversationnel (crée/poursuit une conversation).
  - `POST /api/v1/assistant/generate-form/` — génère un schéma JSON compatible `FormSchema.schema` à partir d'un prompt.
  - `GET/DELETE /api/v1/assistant/conversations/[id]/` — gestion de l'historique.
- Sécurité : isolation par owner, fallback texte si l'API Gemini tombe.
- Tests : 25 tests verts (mocks sur `gemini_client.generate_text`).

## Choix technique — Mobile Money

**Décision : FedaPay en principal, KkiaPay en fallback / pay-as-you-go.**

### Exigence produit
Le client (gérant de WiFi Zone) doit pouvoir **saisir uniquement son numéro de téléphone** — pas de choix manuel d'opérateur (MTN MoMo / Moov Money). Le backend doit détecter automatiquement le réseau à partir du numéro et router le paiement.

### FedaPay (choix principal)
- Société **béninoise** (Cotonou) → support local, facturation FCFA, proximité commerciale
- Couvre MTN MoMo + Moov Money au Bénin, plus cartes bancaires
- S'étend à Côte d'Ivoire, Sénégal, Togo, Guinée, Niger (utile pour l'expansion)
- **Auto-détection du réseau** depuis le numéro
- API REST + SDK Python + webhooks + mode test/live
- Gestion des **paiements récurrents** → adapté aux abonnements SaaS mensuels (Starter / Pro / Business)
- Tarifs ~1,5 à 2 % par transaction, pas de frais d'installation

### KkiaPay (fallback / one-shot)
- Également **béninoise**
- Widget checkout ultra-simple (1 ligne de JS) + API backend
- Auto-détection MTN/Moov depuis le numéro
- Excellent pour le modèle **pay-as-you-go** (ex. 1 000 FCFA pour 50 leads)
- Moins mature que FedaPay sur les abonnements récurrents

### Écartés
- **PayDunya** (Sénégal) : solide mais moins de feeling local au Bénin
- **CinetPay** : orienté Côte d'Ivoire, support Bénin plus faible
- **Flutterwave** : présence MoMo UEMOA francophone instable
- **Paystack** : pas encore solide sur MoMo francophone

### Ce que ça implique côté backend (à implémenter)
- Nouvelle app Django `billing/` avec modèles `Plan`, `Subscription`, `Transaction`, `LeadQuota`
- Endpoint `POST /billing/pay/` → `{phone, amount, plan_id}` → FedaPay → URL de confirmation
- Webhook `POST /billing/webhook/fedapay/` pour activer l'abonnement après paiement
- Middleware de quota sur `/portal/submit/` pour bloquer quand le quota de leads est atteint

---

## Pistes produit à prioriser ensuite

- **Plans d'abonnement** : Starter (3-5k FCFA), Pro (10-15k), Business (25k+) + essai gratuit 30j / 50 leads
- **Multi-points d'accès** : aujourd'hui `FormSchema` est en OneToOne avec `User`, à passer en 1-à-N pour le plan Business multi-sites
- **Consentement RGPD explicite** dans `FormSchema` (case à cocher marketing) — requis pour la revente de données agrégées B2B2B
- **Export ARCEP** : endpoint `/leads/export-arcep/` avec format standardisé pour faciliter les réquisitions
- **SMS/WhatsApp** : `messages_services.py` existe mais le branchement à un provider (Orange SMS API, Twilio, WhatsApp Business API) reste à vérifier/faire

---

**Dernière mise à jour : 21/04/2026**
