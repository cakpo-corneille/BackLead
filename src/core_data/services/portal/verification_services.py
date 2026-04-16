from typing import Dict, Any, Optional
import uuid


from django.contrib.auth import get_user_model

from .messages_services import verify_code


from core_data.models import FormSchema, OwnerClient
from config.utils.sender import send_code_async_or_sync
import logging
logger = logging.getLogger(__name__)

User = get_user_model()


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
    
    Args:
        form_schema: Instance du FormSchema
        mac_address: Adresse MAC du device
        email: Email normalisé (optionnel)
        phone: Téléphone normalisé (optionnel)
        client_token: Token du client (optionnel)
    
    Returns:
        {
            'exists': bool,
            'client': OwnerClient | None,
            'method': 'mac' | 'token' | 'email' | 'phone' | None,
            'conflict_field': 'email' | 'phone' | None,
            'is_verified': bool  # Si le client existe et est vérifié
        }
    """
    mac_address = mac_address.upper().strip()
    
    # 1️⃣ Vérification par MAC address (prioritaire)
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
    
    # 2️⃣ Vérification par client_token
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
    
    # 3️⃣ Vérification par phone (conflit potentiel)
    if phone:
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
    
    # 4️⃣ Client non trouvé
    return {
        'exists': False,
        'client': None,
        'method': None,
        'conflict_field': None,
        'is_verified': False
    }



def _handle_device_recognition(
    client: OwnerClient,
    payload: dict,
    email: Optional[str],
    phone: Optional[str],
    form_schema: FormSchema
) -> dict:
    """
    Gère la mise à jour d'un client reconnu par son device.
    Pas de vérification requise (même device).
    """
    # Mise à jour des données
    client.payload = payload
    if email:
        client.email = email
    if phone:
        client.phone = phone
    client.save()
    
    # Double opt-in si activé et non vérifié
    requires_verification = form_schema.double_opt_enable and not client.is_verified
    
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


def _handle_contact_conflict(
    client: OwnerClient,
    mac_address: str,
    payload: dict,
    email: Optional[str],
    phone: Optional[str],
    conflict_field: str,
    verification_code: Optional[str],
    form_schema: FormSchema
) -> dict:
    """
    Gère un conflit par téléphone uniquement.
    Si le téléphone est reconnu sur un autre appareil, on demande l'OTP.
    """
    # A) Aucun code fourni → envoyer code et attendre
    if not verification_code:
        send_code_async_or_sync(client)
        
        return {
            'created': False,
            'duplicate': True,
            'client_token': client.client_token,
            'requires_verification': False,
            'verification_pending': True,
            'conflict_field': conflict_field,
            'message': 'Ce numéro de téléphone est déjà associé à un autre appareil. Un code de vérification a été envoyé par SMS.'
        }
    
    # B) Code fourni → vérifier
    success, error_msg = verify_code(client, verification_code)
    
    if not success:
        return {
            'created': False,
            'duplicate': True,
            'client_token': None,
            'requires_verification': False,
            'verification_pending': True,
            'conflict_field': conflict_field,
            'error': error_msg
        }
    
    # C) Code validé → association au device
    client.mac_address = mac_address
    client.payload = payload
    
    if email:
        client.email = email
    if phone:
        client.phone = phone
    
    # Générer nouveau token pour le nouveau device
    if not client.client_token:
        client.client_token = str(uuid.uuid4())
    client.recognition_level += 1
    client.save()
    
    return {
        'created': False,
        'duplicate': True,
        'client_token': client.client_token,
        'requires_verification': False,
        'verification_pending': False,
        'conflict_field': None,
        'message': 'Compte associé à ce nouvel appareil avec succès.'
    }


def _create_new_client(
    form_schema: FormSchema,
    mac_address: str,
    payload: dict,
    email: Optional[str],
    phone: Optional[str],
    client_token: Optional[str]
) -> dict:
    """
    Crée un nouveau client (personne + device inconnus).
    """
    client = OwnerClient.objects.create(
        owner=form_schema.owner,
        mac_address=mac_address,
        payload=payload,
        email=email or None,
        phone=phone or None,
        client_token=client_token or str(uuid.uuid4())
    )
    
    # Double opt-in si activé
    requires_verification = form_schema.double_opt_enable
    
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