from typing import Dict, Any, Optional, Tuple
import uuid
import re
import unicodedata

from django.contrib.auth import get_user_model

from .messages_services import verify_code

from core_data.models import FormSchema, OwnerClient, ClientDevice
from config.utils.sender import send_code_async_or_sync
import logging

logger = logging.getLogger(__name__)

User = get_user_model()


# ─────────────────────────────────────────────────────────────────────────
# UTILITAIRES D'EXTRACTION DE NOMS
# ─────────────────────────────────────────────────────────────────────────

def _extract_names_from_payload(payload: Dict[str, Any]) -> Tuple[Optional[str], Optional[str]]:
    """
    Extrait (last_name, first_name) depuis le payload soumis par le widget.

    Gère trois cas :
    1. Champs dédiés prénom (first_name, prenom, prénom…) et nom (last_name, nom…)
       détectés par regex pour couvrir toutes les variantes de nommage.
    2. Champs combinés (nom_prenom, fullname, nom_et_prenom…) : le dernier mot
       devient le nom de famille, le reste le prénom.
    3. Champ unique (un seul mot) : assigné au nom de famille par défaut.

    Retourne (last_name, first_name) — les deux peuvent être None si le payload
    ne contient aucun champ reconnaissable.
    """
    first_name = None
    last_name = None

    if not payload or not isinstance(payload, dict):
        return None, None

    first_patterns    = r'(first_?name|prenom|prénom)(?!.*last)'
    last_patterns     = r'(last_?name|nom)(?!.*first)'
    combined_patterns = r'(nom_?prenom|nomprenoms?|nom_et_?prenom|prenom_?et_?nom|full_?name|fullname)'

    for key, value in payload.items():
        if not value or not isinstance(value, str):
            continue

        key_lower = key.lower().replace('-', '_')

        # Cas 1 : champ combiné → dernier mot = nom, le reste = prénom
        if re.search(combined_patterns, key_lower):
            parts = value.strip().split()
            if len(parts) >= 2:
                last_name  = parts[-1]
                first_name = ' '.join(parts[:-1])
            elif len(parts) == 1:
                last_name = parts[0]
            continue

        # Cas 2 : champ prénom seul
        if re.search(first_patterns, key_lower) and not first_name:
            first_name = value.strip()

        # Cas 3 : champ nom seul
        if re.search(last_patterns, key_lower) and not last_name:
            last_name = value.strip()

    return last_name, first_name


# ─────────────────────────────────────────────────────────────────────────
# UTILITAIRES DE DEVICE
# ─────────────────────────────────────────────────────────────────────────

def _upsert_device(client: OwnerClient, mac_address: str, user_agent: str = '') -> None:
    """
    Crée ou met à jour le tuple (mac_address, user_agent) dans ClientDevice.
    last_seen est mis à jour automatiquement via auto_now.
    """
    device, created = ClientDevice.objects.get_or_create(
        client=client,
        mac_address=mac_address.upper().strip(),
        defaults={'user_agent': user_agent}
    )
    if not created and user_agent:
        device.user_agent = user_agent
        device.save(update_fields=['user_agent', 'last_seen'])



# ─────────────────────────────────────────────────────────────────────────
# DÉTECTION DE CLIENT EXISTANT
# ─────────────────────────────────────────────────────────────────────────

def detect_existing_client(
    form_schema: FormSchema,
    mac_address: str,
    email: Optional[str] = None,
    phone: Optional[str] = None,
    client_token: Optional[str] = None
) -> dict:
    """
    Détecte si un client existe déjà dans la base.

    Logique de détection (par ordre de priorité) :
    1. Par MAC address (même device)
    2. Par client_token (même personne, reconnaissance cross-device)
    3. Par email (même personne, device différent → conflit potentiel)
    4. Par phone (même personne, device différent → conflit potentiel)

    Returns:
        {
            'exists': bool,
            'client': OwnerClient | None,
            'method': 'mac' | 'token' | 'email' | 'phone' | None,
            'conflict_field': 'email' | 'phone' | None,
            'is_verified': bool
        }
    """
    mac_address = mac_address.upper().strip()

    client = OwnerClient.objects.filter(
        owner=form_schema.owner,
        mac_address=mac_address
    ).first()

    if client:
        return {
            'exists': True,
            'client': client,
            'method': 'mac',
            'conflict_field': None,
            'is_verified': client.is_verified
        }

    if client_token:
        client = OwnerClient.objects.filter(
            owner=form_schema.owner,
            client_token=client_token
        ).first()

        if client:
            return {
                'exists': True,
                'client': client,
                'method': 'token',
                'conflict_field': None,
                'is_verified': client.is_verified
            }

    email_required = any(
        f.get('required') for f in form_schema.schema.get('fields', [])
        if f.get('type') == 'email'
    )
    if email and email_required:
        client = OwnerClient.objects.filter(
            owner=form_schema.owner,
            email=email
        ).first()

        if client:
            return {
                'exists': True,
                'client': client,
                'method': 'email',
                'conflict_field': 'email',
                'is_verified': client.is_verified
            }

    phone_types = ('phone', 'tel', 'whatsapp')
    phone_required = any(
        f.get('required') for f in form_schema.schema.get('fields', [])
        if f.get('type') in phone_types
    )
    if phone and phone_required:
        client = OwnerClient.objects.filter(
            owner=form_schema.owner,
            phone=phone
        ).first()

        if client:
            return {
                'exists': True,
                'client': client,
                'method': 'phone',
                'conflict_field': 'phone',
                'is_verified': client.is_verified
            }

    return {
        'exists': False,
        'client': None,
        'method': None,
        'conflict_field': None,
        'is_verified': False
    }


# ─────────────────────────────────────────────────────────────────────────
# VÉRIFICATION OTP
# ─────────────────────────────────────────────────────────────────────────

def verify_client_code(client: OwnerClient, code: str) -> Tuple[bool, str]:
    """
    Vérifie le code OTP et résout les alertes en attente si succès.
    """
    success, error_msg = verify_code(client, code)

    if success:
        client.is_verified = True
        client.save()

        from core_data.models import ConflictAlert
        ConflictAlert.objects.filter(
            existing_client=client,
            status='PENDING'
        ).update(status='RESOLVED')

    return success, error_msg


# ─────────────────────────────────────────────────────────────────────────
# HANDLERS DE CLIENTS
# ─────────────────────────────────────────────────────────────────────────

def _handle_device_recognition(
    client: OwnerClient,
    payload: dict,
    email: Optional[str],
    phone: Optional[str],
    form_schema: FormSchema,
    user_agent: str = ''
) -> dict:
    """
    Gère la mise à jour d'un client reconnu par son device (MAC ou token).
    Pas de vérification requise (même device).
    """
    client.payload = payload
    if email:
        client.email = email
    if phone:
        client.phone = phone
    if user_agent:
        client.user_agent = user_agent

    last_name, first_name = _extract_names_from_payload(payload)
    if last_name:
        client.last_name = last_name
    if first_name:
        client.first_name = first_name

    client.save()
    _upsert_device(client, client.mac_address, user_agent)

    requires_verification = form_schema.opt and not client.is_verified

    if requires_verification:
        send_code_async_or_sync(client)

    return {
        'created': False,
        'duplicate': True,
        'client_token': client.client_token,
        'requires_verification': requires_verification,
        'verification_pending': False,
        'conflict_field': None,
        'message': 'Données mises à jour avec succès.'
    }


def _create_new_client(
    form_schema: FormSchema,
    mac_address: str,
    payload: dict,
    email: Optional[str],
    phone: Optional[str],
    user_agent: str = ''
) -> dict:
    """
    Crée un nouveau client (personne + device inconnus).

    Le client_token est TOUJOURS généré côté serveur via uuid.uuid4().
    On n'accepte jamais un token venant du frontend pour éviter qu'un token
    persisté dans le localStorage d'un ancien device puisse "ressusciter"
    un profil supprimé ou usurper l'identité d'un client existant.
    """
    last_name, first_name = _extract_names_from_payload(payload)

    client = OwnerClient.objects.create(
        owner=form_schema.owner,
        mac_address=mac_address,
        payload=payload,
        email=email or None,
        phone=phone or None,
        first_name=first_name,
        last_name=last_name,
        client_token=str(uuid.uuid4()),  # toujours généré côté serveur
        user_agent=user_agent or ''
    )
    _upsert_device(client, mac_address, user_agent)

    requires_verification = form_schema.opt

    if requires_verification:
        send_code_async_or_sync(client)

    return {
        'created': True,
        'duplicate': False,
        'client_token': client.client_token,
        'requires_verification': requires_verification,
        'verification_pending': False,
        'conflict_field': None,
        'message': 'Compte créé avec succès.'
    }
