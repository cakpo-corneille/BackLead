from typing import Dict, Any, Optional, Tuple
import uuid

from django.contrib.auth import get_user_model

from .messages_services import verify_code

from core_data.models import FormSchema, OwnerClient, ClientDevice
from config.utils.sender import send_code_async_or_sync
import logging

logger = logging.getLogger(__name__)

User = get_user_model()


def _extract_names_from_payload(payload: dict) -> Tuple[str, str]:
    """
    Extrait (last_name, first_name) depuis le payload soumis par le widget.

    Logique :
    1. Champ prénom dédié (prenom, prénom, firstname, first_name) → first_name
    2. Champ nom dédié (nom, last_name, lastname) :
       - Si first_name déjà trouvé → toute la valeur = last_name
       - Sinon et valeur composite (plusieurs mots) → premier mot = last_name, reste = first_name
       - Sinon → last_name uniquement
    3. Champs composites (name, nom_complet, nom_prenom, …) si rien trouvé →
       premier mot = last_name, reste = first_name
    """
    if not payload or not isinstance(payload, dict):
        return '', ''

    first_name = ''
    last_name = ''

    for key in ('prenom', 'prénom', 'firstname', 'first_name'):
        val = payload.get(key)
        if val and str(val).strip():
            first_name = str(val).strip()
            break

    for key in ('nom', 'last_name', 'lastname'):
        val = payload.get(key)
        if val and str(val).strip():
            cleaned = str(val).strip()
            parts = cleaned.split()
            if first_name or len(parts) == 1:
                last_name = cleaned
            else:
                last_name = parts[0]
                first_name = ' '.join(parts[1:])
            break

    if not first_name and not last_name:
        for key in ('name', 'nom_complet', 'nom_prenom', 'nom_prenoms', 'nom_et_prenom', 'nom_etprenoms'):
            val = payload.get(key)
            if val and str(val).strip():
                parts = str(val).strip().split()
                if len(parts) >= 2:
                    last_name = parts[0]
                    first_name = ' '.join(parts[1:])
                else:
                    last_name = parts[0]
                break

    return last_name, first_name


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


def _names_match(last1: str, first1: str, last2: str, first2: str) -> bool:
    """
    Compare deux paires (nom, prénom) de façon insensible à la casse.
    Retourne False si l'une des deux paires est vide (indéterminé → pas de match).
    """
    if not (last1 or first1) or not (last2 or first2):
        return False
    return (
        last1.strip().lower() == last2.strip().lower() and
        first1.strip().lower() == first2.strip().lower()
    )


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
    1. Par MAC address ou client_token (même device)
    2. Par email (même personne, device différent)
    3. Par phone (même personne, device différent)

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


def _handle_silent_attachment(
    client: OwnerClient,
    mac_address: str,
    payload: dict,
    email: Optional[str],
    phone: Optional[str],
    form_schema: FormSchema,
    user_agent: str = ''
) -> dict:
    """
    Niveau 2 — Rattache silencieusement un nouveau device à un client existant
    dont les noms correspondent (même personne, nouvel appareil).
    Zéro friction, zéro alerte.
    """
    client.mac_address = mac_address
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
    _upsert_device(client, mac_address, user_agent)

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
        'message': 'Appareil associé à votre compte avec succès.'
    }


def _create_new_client(
    form_schema: FormSchema,
    mac_address: str,
    payload: dict,
    email: Optional[str],
    phone: Optional[str],
    client_token: Optional[str],
    user_agent: str = ''
) -> dict:
    """
    Crée un nouveau client (personne + device inconnus, ou "Non c'est pas moi").
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
        client_token=client_token or str(uuid.uuid4()),
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
