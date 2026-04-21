"""
Services métier de l'app assistant : chat conversationnel et génération
de schémas de formulaires.
"""
import json
import logging
from typing import Optional

from . import gemini_client
from .models import ChatConversation, ChatMessage

logger = logging.getLogger(__name__)


# ============================================================
# Prompts système
# ============================================================

SYSTEM_PROMPT_CHAT = """\
Tu es l'assistant IA de WiFiLeads, une plateforme SaaS qui permet aux
propriétaires de hotspots WiFi (cybercafés, hôtels, restaurants) en
Afrique de l'Ouest (Bénin, Togo) de collecter des leads via un widget
de formulaire affiché sur leur portail captif.

Ton rôle :
- Aider les owners à comprendre la plateforme.
- Les guider pour créer/configurer leurs formulaires (champs disponibles :
  text, email, phone, choice, checkbox, date, textarea).
- Expliquer les statistiques : sessions WiFi, leads collectés, plans tarifaires (TicketPlan).
- Donner des conseils marketing/produit adaptés au contexte ouest-africain
  (Mobile Money, MTN/Moov, faible bande passante, multilinguisme FR/local).
- Être concis, factuel, en français par défaut. Si l'owner écrit en anglais,
  réponds en anglais.

Tu N'AS PAS accès aux données privées de l'owner sauf si elles te sont
explicitement transmises dans le contexte. Ne fais jamais semblant de
connaître ses chiffres réels.

Quand on te demande de générer un formulaire, propose la structure JSON
attendue : { "fields": [ { "name", "label", "type", "required" } ] }.
"""

SYSTEM_PROMPT_FORM_GENERATOR = """\
Tu es un expert UX qui génère des schémas de formulaires de collecte de
leads pour portails captifs WiFi.

Réponds UNIQUEMENT au format JSON suivant, rien d'autre :
{
  "title": "...",
  "description": "...",
  "button_label": "...",
  "fields": [
    { "name": "snake_case", "label": "Libellé FR", "type": "TYPE", "required": true|false }
  ]
}

Types de champs autorisés : text, email, phone, choice, checkbox, date, textarea.
- Pour 'choice', ajoute "options": ["a", "b", "c"].
- Reste minimaliste : 3-5 champs maximum, le portail captif doit rester rapide à remplir.
- Toujours inclure au moins un moyen de contact (email OU phone).
- Les noms de champs sont en snake_case anglais ; les labels sont en français.
"""


# ============================================================
# Chat
# ============================================================

def chat(
    owner,
    user_message: str,
    conversation: Optional[ChatConversation] = None,
    history_limit: int = 20,
) -> tuple[ChatConversation, ChatMessage]:
    """
    Envoie un message à l'IA et persiste la conversation.

    Args:
        owner: User propriétaire de la conversation.
        user_message: texte saisi par l'owner.
        conversation: conversation existante, ou None pour en créer une.
        history_limit: nombre max de messages précédents passés à l'IA.

    Returns:
        (conversation, assistant_message)
    """
    if conversation is None:
        conversation = ChatConversation.objects.create(
            owner=owner,
            title=user_message[:100],
        )
    elif conversation.owner_id != owner.id:
        raise PermissionError("Conversation n'appartenant pas à cet owner.")

    # Persist user message d'abord
    ChatMessage.objects.create(
        conversation=conversation,
        role=ChatMessage.ROLE_USER,
        content=user_message,
    )

    # Construit l'historique
    previous = list(
        conversation.messages
        .order_by('-created_at')[:history_limit]
        .values('role', 'content')
    )
    previous.reverse()
    # On retire le dernier (= le user_message qu'on vient d'ajouter)
    history = previous[:-1] if previous else []

    try:
        reply_text = gemini_client.generate_text(
            prompt=user_message,
            system_instruction=SYSTEM_PROMPT_CHAT,
            history=history,
        )
    except Exception as exc:
        logger.exception("[assistant] Échec appel Gemini : %s", exc)
        reply_text = (
            "Désolé, l'assistant est temporairement indisponible. "
            "Réessayez dans un instant."
        )

    assistant_msg = ChatMessage.objects.create(
        conversation=conversation,
        role=ChatMessage.ROLE_MODEL,
        content=reply_text,
    )
    # Touche updated_at
    conversation.save(update_fields=['updated_at'])
    return conversation, assistant_msg


# ============================================================
# Génération de formulaire
# ============================================================

ALLOWED_FIELD_TYPES = {'text', 'email', 'phone', 'choice', 'checkbox', 'date', 'textarea'}


def generate_form_schema(prompt: str) -> dict:
    """
    Demande à Gemini un schéma de formulaire à partir d'une description libre.

    Args:
        prompt: description de l'owner (ex : "Je veux collecter nom, email
                et type de business pour mon cybercafé").

    Returns:
        dict prêt à être stocké dans FormSchema.schema, contenant au minimum :
        { "fields": [ ... ] }, et idéalement title/description/button_label.

    Raises:
        ValueError: si la réponse est invalide après tentative de parsing.
    """
    raw = gemini_client.generate_text(
        prompt=prompt,
        system_instruction=SYSTEM_PROMPT_FORM_GENERATOR,
        response_mime_type='application/json',
    )

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Réponse IA non JSON : {exc}") from exc

    if not isinstance(data, dict) or 'fields' not in data:
        raise ValueError("Schéma invalide : clé 'fields' manquante.")
    if not isinstance(data['fields'], list) or not data['fields']:
        raise ValueError("Schéma invalide : 'fields' doit être une liste non vide.")

    cleaned_fields = []
    for f in data['fields']:
        if not isinstance(f, dict):
            continue
        ftype = f.get('type')
        if ftype not in ALLOWED_FIELD_TYPES:
            continue
        cleaned = {
            'name': str(f.get('name', '')).strip(),
            'label': str(f.get('label', '')).strip(),
            'type': ftype,
            'required': bool(f.get('required', False)),
        }
        if not cleaned['name'] or not cleaned['label']:
            continue
        if ftype == 'choice' and isinstance(f.get('options'), list):
            cleaned['options'] = [str(o) for o in f['options']]
        cleaned_fields.append(cleaned)

    if not cleaned_fields:
        raise ValueError("Aucun champ valide généré.")

    return {
        'title': str(data.get('title', '')).strip() or 'Bienvenue !',
        'description': str(data.get('description', '')).strip(),
        'button_label': str(data.get('button_label', '')).strip() or 'Accéder au WiFi',
        'fields': cleaned_fields,
    }
