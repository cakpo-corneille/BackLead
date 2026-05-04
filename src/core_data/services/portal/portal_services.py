from typing import Dict, Any, Optional
import logging
from django.contrib.auth import get_user_model
from django.shortcuts import get_object_or_404

from core_data.models import FormSchema, OwnerClient
from .verification_services import (
    _create_new_client,
    _handle_device_recognition,
    _handle_silent_attachment,
    _names_match,
    _extract_names_from_payload,
    detect_existing_client
)
from core_data.services.dashboard.analytics import invalidate_analytics_cache

logger = logging.getLogger(__name__)

User = get_user_model()


def get_owner_info(user: User, request=None) -> Dict[str, Any]:  # type: ignore
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


def _maybe_create_conflict_alert(
    owner,
    existing_client: OwnerClient,
    conflict_field: str,
    payload: dict,
    mac_address: str
) -> None:
    """
    Crée une ConflictAlert si elle n'existe pas déjà pour ce cas précis.
    Se déclenche uniquement lors d'un cas ambigu confirmé ("Oui c'est moi" avec noms différents).
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
        try:
            from config.utils.sender import notify_conflict_alert
            notify_conflict_alert(alert)
        except Exception as e:
            logger.warning(f"notify_conflict_alert échoué : {e}")


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
        → Mise à jour silencieuse du client existant. Aucun questionnement.
        → Pas de création de doublon, pas d'alerte.

    Niveau 2 — Conflit détecté (email/téléphone connu, device inconnu)
        → Règle absolue : on n'écrase JAMAIS le client existant.
        → Cas particulier (payload identique) : rattachement silencieux du
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

    last_name_val, first_name_val = _extract_names_from_payload(payload)

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
    #   - soit un rattachement de device (même payload = même personne évidente)
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

        # Cas spécial : même payload exact + même contact → simple rattachement
        # de device, c'est manifestement la même personne sur un nouvel appareil.
        # On rattache sans créer de doublon, mais on alerte quand même le owner.
        payloads_identical = (existing_client.payload == payload)
        if payloads_identical:
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
