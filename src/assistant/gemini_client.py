"""
Wrapper autour du SDK google-genai branché sur Replit AI Integrations.
Aucune clé API à gérer : les variables d'env AI_INTEGRATIONS_GEMINI_*
sont injectées automatiquement par Replit.

Modèles supportés via AI Integrations :
- gemini-2.5-flash  : usage quotidien, rapide
- gemini-2.5-pro    : raisonnement complexe
"""
import os
from functools import lru_cache

from google import genai
from google.genai import types


# IMPORTANT: KEEP THIS COMMENT
# Intégration Replit AI Integrations — pas d'API key à fournir.
# AI_INTEGRATIONS_GEMINI_API_KEY contient une valeur factice : ne pas la
# valider en testant simplement sa valeur, faire un vrai appel.

DEFAULT_MODEL = 'gemini-2.5-flash'
PRO_MODEL = 'gemini-2.5-pro'


@lru_cache(maxsize=1)
def get_client() -> genai.Client:
    """Retourne le client Gemini (singleton)."""
    return genai.Client(
        api_key=os.environ.get('AI_INTEGRATIONS_GEMINI_API_KEY'),
        http_options={
            'api_version': '',
            'base_url': os.environ.get('AI_INTEGRATIONS_GEMINI_BASE_URL'),
        },
    )


def generate_text(
    prompt: str,
    *,
    system_instruction: str | None = None,
    history: list[dict] | None = None,
    model: str = DEFAULT_MODEL,
    response_schema=None,
    response_mime_type: str | None = None,
    max_output_tokens: int = 8192,
) -> str:
    """
    Génère une réponse texte.

    Args:
        prompt: message courant de l'utilisateur.
        system_instruction: contexte permanent (rôle de l'IA).
        history: liste de messages précédents [{'role': 'user'|'model', 'content': '...'}].
        response_schema: classe Pydantic pour réponse structurée (force JSON).
        response_mime_type: 'application/json' si on veut du JSON brut.

    Returns:
        Le texte de la réponse (str).
    """
    contents = []
    for msg in (history or []):
        contents.append(types.Content(
            role=msg['role'],
            parts=[types.Part(text=msg['content'])],
        ))
    contents.append(types.Content(
        role='user',
        parts=[types.Part(text=prompt)],
    ))

    config_kwargs = {'max_output_tokens': max_output_tokens}
    if system_instruction:
        config_kwargs['system_instruction'] = system_instruction
    if response_schema is not None:
        config_kwargs['response_schema'] = response_schema
        config_kwargs['response_mime_type'] = 'application/json'
    elif response_mime_type:
        config_kwargs['response_mime_type'] = response_mime_type

    response = get_client().models.generate_content(
        model=model,
        contents=contents,
        config=types.GenerateContentConfig(**config_kwargs),
    )
    return response.text or ''
