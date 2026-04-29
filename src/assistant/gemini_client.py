"""
Wrapper autour du SDK officiel google-genai branché directement sur
l'API Google Gemini (Google AI Studio).

Configuration : ajouter dans le fichier .env à la racine :

    GEMINI_API_KEY=votre_clé_obtenue_sur_https://aistudio.google.com/apikey

Modèles supportés :
- gemini-2.5-flash  : rapide, usage quotidien
- gemini-2.5-pro    : raisonnement complexe
"""
import os
from functools import lru_cache

from google import genai
from decouple import config
from google.genai import types


DEFAULT_MODEL = 'gemini-2.5-flash'
PRO_MODEL = 'gemini-2.5-pro'


@lru_cache(maxsize=1)
def get_client() -> genai.Client:
    """Retourne le client Gemini (singleton).

    Lit la clé via `GEMINI_API_KEY` (ou `GOOGLE_API_KEY` à défaut).
    Lève RuntimeError si aucune clé n'est configurée.
    """
    api_key = config('GEMINI_API_KEY', default=None) or config('GOOGLE_API_KEY', default=None)
    if not api_key:
        raise RuntimeError(
            "GEMINI_API_KEY est manquante. Ajoutez-la dans votre fichier .env "
            "(obtenez-la gratuitement sur https://aistudio.google.com/apikey)."
        )
    return genai.Client(api_key=api_key)


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
