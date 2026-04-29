# Assistant App — Documentation Backend

**Version :** 1.0
**Date :** Avril 2026
**Public :** Développeurs Backend, DevOps, Maintenance

---

## Architecture

L'application `assistant` intègre **Google Gemini** pour offrir aux
owners deux services :

1. Un **agent conversationnel** dédié au domaine WiFi marketing,
   capable de guider l'owner dans la configuration de la plateforme
   et de répondre à ses questions.
2. Un **générateur de schémas de formulaires** : à partir d'une
   description en langage naturel, l'IA produit un JSON directement
   compatible avec `core_data.FormSchema.schema`.

**Composants :**
- 2 modèles : `ChatConversation` + `ChatMessage` (historique persisté)
- Wrapper SDK `google-genai` autour de l'API Google Gemini
- Validation stricte des schémas générés (whitelist des types)
- Isolation par owner sur toutes les opérations

---

## Modèles

### ChatConversation

Un thread de discussion entre un owner et l'IA.

```python
class ChatConversation(models.Model):
    owner      = ForeignKey(User, related_name='chat_conversations')
    public_id  = UUIDField(default=uuid.uuid4, unique=True, editable=False)
    title      = CharField(max_length=200, blank=True, default='')
    created_at = DateTimeField(auto_now_add=True)
    updated_at = DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']
        indexes  = [Index(fields=['owner', '-updated_at'])]
```

- `public_id` permet d'exposer une référence opaque sans révéler l'ID interne.
- `title` est rempli automatiquement avec les 100 premiers caractères
  du premier message si laissé vide.

---

### ChatMessage

Un message d'un thread (rôles `user` ou `model`).

```python
class ChatMessage(models.Model):
    ROLE_USER  = 'user'
    ROLE_MODEL = 'model'

    conversation = ForeignKey(ChatConversation, related_name='messages')
    role         = CharField(max_length=10, choices=[(ROLE_USER, 'User'),
                                                     (ROLE_MODEL, 'Model')])
    content      = TextField()
    created_at   = DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']
        indexes  = [Index(fields=['conversation', 'created_at'])]
```

---

## Client Gemini

**Fichier :** `assistant/gemini_client.py`

Wrapper minimal autour du SDK officiel `google-genai`.

### Configuration

```bash
# .env (à la racine du projet)
GEMINI_API_KEY=votre_clé_API
# ou GOOGLE_API_KEY=...
```

Obtenez gratuitement une clé sur https://aistudio.google.com/apikey.

### Modèles supportés

| Constante       | Modèle              | Usage                       |
|-----------------|---------------------|------------------------------|
| `DEFAULT_MODEL` | `gemini-2.5-flash`  | Quotidien, rapide (défaut)   |
| `PRO_MODEL`     | `gemini-2.5-pro`    | Raisonnement complexe        |

### Fonctions

#### `get_client()`

Singleton client `genai.Client(api_key=...)`. Lève `RuntimeError` si la
clé est absente. Ne jamais reconstruire le client à chaque appel.

#### `generate_text(prompt, *, system_instruction=None, history=None, model='gemini-2.5-flash', response_schema=None, response_mime_type=None, max_output_tokens=8192) -> str`

Appel générique.

| Paramètre            | Description                                                       |
|----------------------|-------------------------------------------------------------------|
| `prompt`             | Message courant (str)                                             |
| `system_instruction` | Rôle/contexte permanent de l'IA                                   |
| `history`            | `[{'role': 'user'\|'model', 'content': '...'}]`                   |
| `response_schema`    | Classe Pydantic → force une sortie JSON validée                   |
| `response_mime_type` | `'application/json'` pour JSON brut sans schéma                   |
| `max_output_tokens`  | Plafond de tokens en sortie (défaut 8192)                         |

---

## Services métier

**Fichier :** `assistant/services.py`

### Prompts système

Deux prompts inlinés :

- `SYSTEM_PROMPT_CHAT` : positionne l'IA comme experte de la plateforme
  WiFiLeads (collecte de leads en Afrique de l'Ouest, Mobile Money,
  contraintes bande passante, FR par défaut). Précise qu'elle n'a pas
  accès aux données privées sauf si transmises dans le contexte.
- `SYSTEM_PROMPT_FORM_GENERATOR` : impose une réponse JSON stricte au
  format attendu par `FormSchema.schema`, avec la liste des types de
  champs autorisés.

### chat(owner, user_message, conversation=None, history_limit=20)

Envoie un message à l'IA et persiste le thread.

**Comportement :**
1. Crée une nouvelle conversation si `conversation=None`, sinon vérifie
   que celle fournie appartient bien à `owner` (sinon `PermissionError`).
2. Persiste le message utilisateur.
3. Récupère les `history_limit` derniers messages comme historique
   (en retirant le message courant déjà persisté).
4. Appelle `gemini_client.generate_text` avec `SYSTEM_PROMPT_CHAT`.
5. En cas d'exception (réseau, quota, API), persiste un message de
   fallback humain (`"Désolé, l'assistant est temporairement indisponible..."`).
6. Persiste la réponse modèle et touche `updated_at`.

**Returns :** `(conversation: ChatConversation, assistant_msg: ChatMessage)`

---

### generate_form_schema(prompt) -> dict

Génère un schéma directement utilisable dans `FormSchema.schema`.

**Validation :**
- La sortie doit être un JSON parseable.
- Doit contenir `fields` (liste non vide).
- Chaque champ filtré : type ∈ `ALLOWED_FIELD_TYPES`, `name` et `label` non vides.
- Si `type == 'choice'`, `options` (liste de strings) est conservée.
- Si après filtrage il ne reste aucun champ valide → `ValueError`.

**Returns :**
```python
{
    'title': str,
    'description': str,
    'button_label': str,
    'fields': [
        {'name': str, 'label': str, 'type': str, 'required': bool, 'options': [...]?},
        ...
    ],
}
```

**Constante :**
```python
ALLOWED_FIELD_TYPES = {
    'text', 'email', 'phone', 'choice', 'checkbox', 'date', 'textarea'
}
```

---

## ViewSets & Endpoints

### AssistantViewSet (actions atomiques)

**Base :** `/api/v1/assistant/`
**Permissions :** `IsAuthenticated`

| Endpoint         | Méthode | Description                                      |
|------------------|---------|--------------------------------------------------|
| `chat/`          | POST    | Envoie un message à l'IA (crée/poursuit thread)  |
| `generate-form/` | POST    | Génère un schéma de formulaire depuis un prompt  |

---

### ChatConversationViewSet (historique)

**Base :** `/api/v1/assistant/conversations/`
**Permissions :** `IsAuthenticated` — list, retrieve, destroy.

| Endpoint  | Méthode | Description                              |
|-----------|---------|------------------------------------------|
| `/`       | GET     | Liste des conversations de l'owner       |
| `{id}/`   | GET     | Détail d'une conversation + tous les messages |
| `{id}/`   | DELETE  | Supprime la conversation et ses messages |

Le queryset filtre toujours par `owner=self.request.user` → impossible
d'accéder/supprimer celles d'un autre owner (404 silencieux).

---

## Serializers

### ChatRequestSerializer

```python
message         = CharField(min_length=1, max_length=4000)
conversation_id = IntegerField(required=False, allow_null=True)
```

### FormGenerationRequestSerializer

```python
prompt = CharField(min_length=5, max_length=2000)
```

### ChatConversationListSerializer (sans messages)

`id`, `public_id`, `title`, `created_at`, `last_message_at` (alias de
`updated_at`), `messages_count` (annotation `Count('messages')`).

### ChatConversationSerializer (avec messages)

Mêmes champs + `messages: [ChatMessageSerializer]`.

### ChatMessageSerializer

`id`, `role`, `content`, `created_at` (tous read-only).

---

## Codes HTTP côté `generate-form/`

| Code | Cause                                              |
|------|----------------------------------------------------|
| 200  | Schéma généré et validé                            |
| 400  | `prompt` invalide (trop court / trop long / vide)  |
| 401  | Non authentifié                                    |
| 422  | Sortie IA invalide (JSON malformé, aucun champ valide) |
| 503  | Gemini indisponible / quota dépassé / réseau       |

---

## Bonnes pratiques

### Ne jamais bypasser le service `chat()` pour persister manuellement

```python
# ✅ CORRECT
from assistant.services import chat
conv, reply = chat(request.user, "Bonjour")

# ❌ INCORRECT — l'historique passé à l'IA et les fallbacks
# d'erreur ne seront pas appliqués.
ChatMessage.objects.create(conversation=conv, role='user', content='Bonjour')
```

### Mocker `gemini_client.generate_text` dans les tests

```python
@patch('assistant.services.gemini_client.generate_text')
def test_quelque_chose(self, mock_gen):
    mock_gen.return_value = "Réponse mockée"
    ...
```

Les 25 tests de l'app n'effectuent **aucun** appel réseau réel.

### Ne pas faire confiance aveuglément à la sortie de Gemini

`generate_form_schema()` filtre déjà les types non autorisés et les
champs incomplets. Si vous ajoutez d'autres usages, gardez ce pattern :
**toujours valider le JSON renvoyé par l'IA avant de le persister**.

### Garder les conversations courtes

Le paramètre `history_limit=20` (par défaut) borne le contexte envoyé à
Gemini. Augmenter cette valeur fait grimper la facturation rapidement.

---

## Structure fichiers

```
assistant/
├── models.py          # ChatConversation + ChatMessage
├── gemini_client.py   # Wrapper google-genai (singleton, get_client/generate_text)
├── services.py        # chat() + generate_form_schema() + prompts système
├── serializers.py     # DRF serializers (chat + form generation)
├── views.py           # AssistantViewSet + ChatConversationViewSet
├── admin.py           # Conversations + messages inline
├── tests.py           # 25 tests (mocks Gemini)
└── migrations/
    └── 0001_initial.py
```

---

**Documentation mise à jour le 21/04/2026**
