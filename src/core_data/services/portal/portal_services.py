from typing import Dict, Any, Optional, Tuple
import logging
import re
import unicodedata
from difflib import SequenceMatcher
from django.contrib.auth import get_user_model
from django.shortcuts import get_object_or_404
from django.utils import timezone

from core_data.models import FormSchema, OwnerClient, ClientDevice
from .verification_services import (
    _create_new_client,
    _handle_device_recognition,
    _names_match,
    detect_existing_client
)
from core_data.services.dashboard.analytics import invalidate_analytics_cache

logger = logging.getLogger(__name__)

User = get_user_model()


# ─────────────────────────────────────────────────────────────────────────
# ALGORITHMES DE COMPARAISON D'IDENTITÉ
# ─────────────────────────────────────────────────────────────────────────

def _remove_accents(text: str) -> str:
    """Supprime les accents d'une chaîne (é→e, à→a, etc.)."""
    if not text:
        return ""
    nfd = unicodedata.normalize('NFD', text)
    return ''.join(char for char in nfd if unicodedata.category(char) != 'Mn')


def _normalize_name(name: Optional[str]) -> str:
    """
    Normalise un nom pour comparaison.
    - Lowercase
    - Trim (début/fin)
    - Espaces multiples → 1 seul
    - Supprime accents
    - Retourne "" si None/vide
    """
    if not name or not isinstance(name, str):
        return ""
    
    # Lowercase et trim
    normalized = name.lower().strip()
    
    # Espaces multiples → 1 seul
    normalized = re.sub(r'\s+', ' ', normalized)
    
    # Supprime accents
    normalized = _remove_accents(normalized)
    
    return normalized


def _levenshtein_distance(s1: str, s2: str) -> int:
    """Calcule la distance de Levenshtein entre deux chaînes."""
    if len(s1) < len(s2):
        return _levenshtein_distance(s2, s1)
    
    if len(s2) == 0:
        return len(s1)
    
    previous_row = range(len(s2) + 1)
    for i, c1 in enumerate(s1):
        current_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (c1 != c2)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row
    
    return previous_row[-1]


def _string_similarity(s1: str, s2: str) -> float:
    """
    Calcule le score de similitude entre deux chaînes (0-100%).
    Utilise Levenshtein + longueur maximale.
    """
    if not s1 and not s2:
        return 100.0
    if not s1 or not s2:
        return 0.0
    
    max_len = max(len(s1), len(s2))
    distance = _levenshtein_distance(s1, s2)
    similarity = (1 - (distance / max_len)) * 100
    
    return max(0, similarity)


def _extract_names_from_payload(payload: Dict[str, Any]) -> Tuple[Optional[str], Optional[str]]:
    """
    Extrait first_name et last_name du payload.
    Gère variations : nom, prenom, nom_prenom, nomprenoms, etc.
    
    Patterns :
    - first_name, prenom, prénom
    - last_name, nom
    - Champs combinés : nom_prenom, nomprenoms, nom_et_prenom, etc.
    
    Pour champs combinés, assume : premier(s) mot(s) = prénom, dernier = nom
    
    Retourne (first_name, last_name) ou (None, None)
    """
    first_name = None
    last_name = None
    
    if not payload or not isinstance(payload, dict):
        return None, None
    
    # Patterns regex pour détecter les clés
    first_patterns = r'(first_?name|prenom|prénom)(?!.*last)'
    last_patterns = r'(last_?name|nom)(?!.*first)'
    combined_patterns = r'(nom_?prenom|nomprenoms?|nom_et_?prenom|prenom_?et_?nom|full_?name|fullname)'
    
    for key, value in payload.items():
        if not value or not isinstance(value, str):
            continue
        
        key_lower = key.lower().replace('-', '_')
        
        # Cas 1 : champ combiné (nom_prenom, nomprenoms, etc)
        if re.search(combined_patterns, key_lower):
            parts = value.strip().split()
            if len(parts) >= 2:
                # Premier(s) = prénom, dernier(s) = nom
                last_name = parts[-1]
                first_name = ' '.join(parts[:-1])
            elif len(parts) == 1:
                # Seul un mot : assigne au nom par défaut
                last_name = parts[0]
            continue
        
        # Cas 2 : champ prénom seul
        if re.search(first_patterns, key_lower) and not first_name:
            first_name = value.strip()
        
        # Cas 3 : champ nom seul
        if re.search(last_patterns, key_lower) and not last_name:
            last_name = value.strip()
    
    return first_name, last_name


def _calculate_name_similarity(
    existing_first: Optional[str],
    existing_last: Optional[str],
    new_first: Optional[str],
    new_last: Optional[str],
    threshold: float = 90.0
) -> bool:
    """
    Compare deux paires de noms (first_name, last_name) avec fuzzy matching.
    
    Normalise les 4 noms, calcule Levenshtein pour chaque paire,
    retourne True si score moyen ≥ threshold (défaut 90%).
    
    Retourne True si les deux noms sont vides (considéré comme identique par défaut).
    """
    # Normalise
    norm_existing_first = _normalize_name(existing_first)
    norm_existing_last = _normalize_name(existing_last)
    norm_new_first = _normalize_name(new_first)
    norm_new_last = _normalize_name(new_last)
    
    # Si tous vides, considère comme identique
    if (not norm_existing_first and not norm_existing_last and
        not norm_new_first and not norm_new_last):
        return True
    
    # Calcule similitude pour chaque paire
    first_similarity = _string_similarity(norm_existing_first, norm_new_first)
    last_similarity = _string_similarity(norm_existing_last, norm_new_last)
    
    # Score moyen
    avg_similarity = (first_similarity + last_similarity) / 2
    
    logger.info(
        f"Name similarity: first={first_similarity:.1f}%, last={last_similarity:.1f}%, avg={avg_similarity:.1f}%"
    )
    
    return avg_similarity >= threshold


# ─────────────────────────────────────────────────────────────────────────
# HANDLERS DE RECONNAISSANCE ET ATTACHEMENT
# ─────────────────────────────────────────────────────────────────────────

def _handle_silent_attachment(
    client: OwnerClient,
    mac_address: str,
    payload: dict,
    email: str,
    phone: str,
    form_schema: FormSchema,
    user_agent: str = ''
) -> dict:
    """
    Rattache un nouveau device (MAC) à un client existant.
    
    Crée/met à jour une entrée ClientDevice avec la MAC et user_agent.
    NE TOUCHE PAS aux champs du client lui-même (first_name, last_name, etc.).
    
    Retourne dict avec client_token et infos de succès.
    """
    # Crée ou met à jour le device
    device, created = ClientDevice.objects.update_or_create(
        client=client,
        mac_address=mac_address,
        defaults={
            'user_agent': user_agent,
            'last_seen': timezone.now(),
        }
    )
    
    logger.info(
        f"Device {'created' if created else 'updated'}: "
        f"client={client.id}, mac={mac_address}"
    )
    
    return {
        'created': False,
        'duplicate': False,
        'client_token': client.client_token,
        'is_verified': client.is_verified,
        'requires_verification': False,
        'verification_pending': False,
        'message': 'Device rattaché au compte existant.'
    }


def _maybe_create_conflict_alert(
    owner,
    existing_client: OwnerClient,
    conflict_field: str,
    payload: dict,
    mac_address: str
) -> None:
    """
    Crée une ConflictAlert si elle n'existe pas déjà pour ce cas précis.
    Se déclenche lors d'un cas ambigu : device inconnu, contact connu.
    """
    from core_data.models import ConflictAlert
    alert, created = ConflictAlert.objects.get_or_create(
        owner=owner,
        existing_client=existing_client,
        conflict_field=conflict_field,
        offending_mac=mac_address,
        status='PENDING',
        defaults={'offending_payload': payload}
    )
    if created:
        try :
            from config.utils.sender import notify_conflict_alert
            notify_conflict_alert(alert)
         except Exception as e:
            logger.warning(f"notify_conflict_alert échoué : {e}")


# ─────────────────────────────────────────────────────────────────────────
# SERVICES PUBLICS
# ─────────────────────────────────────────────────────────────────────────

def get_owner_info(user: User, request=None) -> Dict[str, Any]:
    """Récupère les infos publiques de l'owner pour le widget."""
    owner_info = {
        'name': None,
        'logo_url': None
    }

    if hasattr(user, 'profile'):
        profile = user.profile
        owner_info['name'] = profile.business_name if profile.business_name else user.email

        if profile.logo and profile.logo.name:
            logo_rel = profile.logo.url
            owner_info['logo_url'] = request.build_absolute_uri(logo_rel) if request else logo_rel
    else:
        owner_info['name'] = user.email

    return owner_info


def recognize(
    public_key: str,
    mac_address: str,
    client_token: Optional[str] = None
) -> Dict[str, Any]:
    """
    Vérifie si un client est déjà connu.

    Returns:
        {
            'recognized': bool,
            'method': str (optionnel),
            'client_token': str (optionnel),
            'is_verified': bool
        }
    """
    form_schema = get_object_or_404(FormSchema, public_key=public_key)

    if mac_address:
        device = ClientDevice.objects.filter(
            client__owner=form_schema.owner,
            mac_address=mac_address
        ).first()

        if device:
            client = device.client
            return {
                'recognized': True,
                'method': 'mac_address',
                'client_token': client.client_token,
                'is_verified': client.is_verified
            }

    if client_token:
        client = OwnerClient.objects.filter(
            owner=form_schema.owner,
            client_token=client_token
        ).first()

        if client:
            return {
                'recognized': True,
                'method': 'client_token',
                'client_token': client.client_token,
                'is_verified': client.is_verified
            }

    return {
        'recognized': False,
        'is_verified': False
    }


def provision(public_key: str, request=None) -> Dict[str, Any]:
    """
    Provisioning : retourne le schéma de formulaire et les infos complètes pour le widget.
    """
    form_schema = get_object_or_404(FormSchema, public_key=public_key)

    owner_info = get_owner_info(form_schema.owner, request=request)

    form_logo_url = None
    if form_schema.logo:
        logo_rel = form_schema.logo.url
        form_logo_url = request.build_absolute_uri(logo_rel) if request else logo_rel

    return {
        'schema': form_schema.schema,
        'owner': owner_info,
        'opt': form_schema.opt,
        'enable': form_schema.enable,
        'title': form_schema.title,
        'description': form_schema.description,
        'button_label': form_schema.button_label,
        'logo_url': form_logo_url,
    }


def ingest(
    form_schema: FormSchema,
    mac_address: str,
    payload: dict,
    client_token: Optional[str] = None,
    verification_code: Optional[str] = None,
    user_agent: str = '',
    identity_confirmed: bool = False
) -> dict:
    """
    Enregistre ou met à jour un lead — logique en 3 niveaux.

    Niveau 1 — Reconnaissance par device (MAC ou token)
        → Mise à jour silencieuse du device. Aucun questionnement.
        → Pas de création de doublon, pas d'alerte.

    Niveau 2 — Conflit détecté (email/téléphone connu, device inconnu)
        → Règle absolue : on n'écrase JAMAIS le client existant.
        
        → Cas particulier (noms similaires ≥ 90%) : rattachement silencieux du
          nouveau device au client existant + alerte owner. Pas de doublon.

        → Stratégie ALLOW :
            Nouveau client créé silencieusement + alerte owner.
            L'utilisateur ne voit rien, zéro friction.

        → Stratégie REQUIRE_OTP :
            Premier passage  → question posée à l'utilisateur ("Est-ce vous ?").
            Deuxième passage → nouveau client créé dans tous les cas + alerte owner.
            Le Oui/Non de l'utilisateur est une info contextuelle pour le owner,
            il ne change pas le résultat : un nouveau client est toujours créé.

    Niveau 3 — Nouveau client (aucune correspondance détectée)
        → Création simple. Vérification OTP envoyée si opt=True.

    Principe absolu : le client passe TOUJOURS. Jamais de blocage.
    """
    email_val = None
    phone_val = None

    for field in form_schema.schema.get('fields', []):
        f_name = field['name']
        f_type = field['type']
        if f_name in payload:
            if f_type == 'email':
                email_val = payload[f_name]
            elif f_type in ('phone', 'tel', 'whatsapp'):
                phone_val = payload[f_name]

    new_first_name, new_last_name = _extract_names_from_payload(payload)

    mac_address = mac_address.upper().strip()

    detection = detect_existing_client(
        form_schema=form_schema,
        mac_address=mac_address,
        email=email_val,
        phone=phone_val,
        client_token=client_token
    )

    # ── Niveau 1 : Client reconnu par device (MAC ou token) ──────────────────
    if detection['exists'] and detection['method'] in ('mac', 'token'):
        return _handle_device_recognition(
            client=detection['client'],
            payload=payload,
            email=email_val,
            phone=phone_val,
            form_schema=form_schema,
            user_agent=user_agent
        )

    # ── Niveau 2 / 3 : Contact connu sur un autre device (CONFLIT) ──────────
    #
    # Règle absolue : on n'écrase JAMAIS le client existant.
    # Un conflit détecté produit toujours :
    #   - soit un rattachement de device (noms similaires ≥ 90%)
    #   - soit un nouveau client créé indépendamment
    #   + toujours une alerte envoyée au owner
    #
    # La stratégie ne joue que sur la friction imposée à l'utilisateur :
    #   ALLOW          → zéro friction, tout se passe en silence
    #   REQUIRE_OTP    → on pose la question "Est-ce bien vous ?" avant d'agir
    #
    if detection['exists'] and detection['conflict_field']:
        existing_client = detection['client']
        conflict_field = detection['conflict_field']

        # Cas spécial : noms similaires ≥ 90% → simple rattachement de device
        # C'est manifestement la même personne sur un nouvel appareil.
        # On rattache sans créer de doublon, mais on alerte quand même le owner.
        names_match = _calculate_name_similarity(
            existing_first=existing_client.first_name,
            existing_last=existing_client.last_name,
            new_first=new_first_name,
            new_last=new_last_name,
            threshold=90.0
        )

        if names_match:
            _maybe_create_conflict_alert(
                owner=form_schema.owner,
                existing_client=existing_client,
                conflict_field=conflict_field,
                payload=payload,
                mac_address=mac_address
            )
            return _handle_silent_attachment(
                client=existing_client,
                mac_address=mac_address,
                payload=payload,
                email=email_val,
                phone=phone_val,
                form_schema=form_schema,
                user_agent=user_agent
            )

        # ── Stratégie ALLOW : nouveau client créé silencieusement + alerte ──
        if form_schema.conflict_strategy == 'ALLOW':
            result = _create_new_client(
                form_schema=form_schema,
                mac_address=mac_address,
                payload=payload,
                email=email_val,
                phone=phone_val,
                client_token=client_token,
                user_agent=user_agent
            )
            _maybe_create_conflict_alert(
                owner=form_schema.owner,
                existing_client=existing_client,
                conflict_field=conflict_field,
                payload=payload,
                mac_address=mac_address
            )
            return result

        # ── Stratégie REQUIRE_OTP : on demande d'abord confirmation ─────────
        # Premier passage (identity_confirmed=False) : on pose la question.
        # L'utilisateur n'est PAS encore enregistré à ce stade.
        if not identity_confirmed:
            return {
                'created': False,
                'duplicate': True,
                'client_token': None,
                'identity_conflict': True,
                'requires_verification': False,
                'verification_pending': False,
                'conflict_field': conflict_field,
                'message': 'Ce contact est déjà associé à un compte. Est-ce bien vous ?'
            }

        # Deuxième passage (identity_confirmed=True, réponse "Oui" ou "Non") :
        # dans les deux cas on crée un nouveau client + alerte.
        # Le "Oui/Non" est juste une info contextuelle pour le owner dans l'alerte.
        result = _create_new_client(
            form_schema=form_schema,
            mac_address=mac_address,
            payload=payload,
            email=email_val,
            phone=phone_val,
            client_token=client_token,
            user_agent=user_agent
        )
        _maybe_create_conflict_alert(
            owner=form_schema.owner,
            existing_client=existing_client,
            conflict_field=conflict_field,
            payload=payload,
            mac_address=mac_address
        )
        return result

    # ── Nouveau client (Cas C) ────────────────────────────────────────────────
    return _create_new_client(
        form_schema=form_schema,
        mac_address=mac_address,
        payload=payload,
        email=email_val,
        phone=phone_val,
        client_token=client_token,
        user_agent=user_agent
    )
