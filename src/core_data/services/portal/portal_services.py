from typing import Dict, Any, Optional
import logging
from django.contrib.auth import get_user_model
from django.shortcuts import get_object_or_404

from core_data.models import FormSchema, OwnerClient
from .verification_services import _create_new_client, _handle_contact_conflict, _handle_device_recognition, detect_existing_client
from core_data.services.dashboard.analytics import invalidate_analytics_cache

logger = logging.getLogger(__name__)

User = get_user_model()



def get_owner_info(user: User, request=None) -> Dict[str, Any]: # type: ignore
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
    
    # 1. Vérifier par MAC address
    if mac_address:
        client = OwnerClient.objects.filter(
            owner=form_schema.owner,
            mac_address=mac_address
        ).first()
        
        if client:
            return {
                'recognized': True,
                'method': 'mac_address',
                'client_token': client.client_token,
                'is_verified': client.is_verified
            }
            
    # 2. Vérifier par client_token
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
    
    Args:
        public_key: UUID de la clé publique
        request: HttpRequest (optionnel, pour construire des URLs absolues)
    
    Returns:
        {
            'schema': {...},
            'owner': {'name': str, 'logo_url': str},
            'double_opt_enable': bool,
            'enable': bool,
            'title': str,
            'description': str,
            'button_label': str,
            'logo_url': str | None,
        }
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
        'double_opt_enable': form_schema.double_opt_enable,
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
    verification_code: Optional[str] = None
) -> dict:
    """
    Enregistre ou met à jour un lead.
    
    Le payload est déjà validé par le serializer.
    
    Args:
        form_schema: Instance du FormSchema
        mac_address: Adresse MAC du device
        payload: Données validées et normalisées
        client_token: Token de reconnaissance (optionnel)
        verification_code: Code de vérification (optionnel)
    
    Returns:
        {
            'created': bool,
            'duplicate': bool,
            'client_token': str,
            'requires_verification': bool,
            'verification_pending': bool,
            'conflict_field': str | None,
            'message': str | None,
            'error': str | None
        }
    """
    
    # 1️⃣ Extraire email et phone du payload (déjà normalisés)
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
    
    mac_address = mac_address.upper().strip()
    
    # 2️⃣ Détecter si le client existe déjà
    detection = detect_existing_client(
        form_schema=form_schema,
        mac_address=mac_address,
        email=email_val,
        phone=phone_val,
        client_token=client_token
    )
    
    # 3️⃣ CAS A : Client reconnu par device (MAC ou token)
    if detection['exists'] and detection['method'] in ['mac', 'token']:
        result = _handle_device_recognition(
            client=detection['client'],
            payload=payload,
            email=email_val,
            phone=phone_val,
            form_schema=form_schema
        )
    
    # 4️⃣ CAS B : Client reconnu par contact (email ou phone)
    elif detection['exists'] and detection['conflict_field']:
        if not form_schema.double_opt_enable:
            result = _create_new_client(
                form_schema=form_schema,
                mac_address=mac_address,
                payload=payload,
                email=email_val,
                phone=phone_val,
                client_token=client_token
            )
        else:
            result = _handle_contact_conflict(
                client=detection['client'],
                mac_address=mac_address,
                payload=payload,
                email=email_val,
                phone=phone_val,
                conflict_field=detection['conflict_field'],
                verification_code=verification_code,
                form_schema=form_schema
            )
    
    # 5️⃣ CAS C : Nouveau client
    else:
        result = _create_new_client(
            form_schema=form_schema,
            mac_address=mac_address,
            payload=payload,
            email=email_val,
            phone=phone_val,
            client_token=client_token
        )

    return result
