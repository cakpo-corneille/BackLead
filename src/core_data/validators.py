from typing import Dict, Any, Tuple, Optional
import phonenumbers
from phonenumbers import NumberParseException, PhoneNumberFormat
from email_validator import validate_email, EmailNotValidError
from django.conf import settings



from typing import Dict, Tuple, List, Any

ALLOWED_TYPES = {"text", "email", "phone", "number", "choice", "boolean"}
MAX_FIELDS = 5
CONTACT_TYPES = {"email", "phone"}


def validate_schema_format(schema: Dict[str, Any]) -> Tuple[bool, str]:
    """
    Valide la structure complète d'un schéma de formulaire envoyé par le dashboard.

    Args:
        schema: dict contenant au minimum la clé 'fields'

    Returns:
        Tuple[bool, str] : (True, "ok") si valide, (False, message) sinon
    """
    if not isinstance(schema, dict):
        return False, "Schema must be a dictionary"

    fields = schema.get("fields")
    if not isinstance(fields, list):
        return False, "Schema must contain a list of 'fields'"

    if len(fields) > MAX_FIELDS:
        return False, f"Maximum number of fields is {MAX_FIELDS}"

    seen_names = set()
    seen_labels = set()
    for idx, field in enumerate(fields):
        if not isinstance(field, dict):
            return False, f"Field at index {idx} must be a dictionary"

        # name
        name = field.get("name")
        if not isinstance(name, str) or not name.strip():
            return False, f"Field at index {idx} must have a non-empty 'name' string"

        if name in seen_names:
            return False, f"Duplicate field name detected: '{name}'"
        seen_names.add(name)

        # label
        label = field.get("label")
        if not isinstance(label, str) or not label.strip():
            return False, f"Field '{name}' must have a non-empty 'label'"

        label_key = label.strip().lower()
        if label_key in seen_labels:
            return False, f"Deux champs ont le même libellé : '{label.strip()}'"
        seen_labels.add(label_key)

        # type
        field_type = field.get("type")
        if field_type not in ALLOWED_TYPES:
            return False, f"Field '{name}' has invalid type '{field_type}'"

        # required
        required = field.get("required", False)
        if not isinstance(required, bool):
            return False, f"Field '{name}': 'required' must be boolean"

        # placeholder
        placeholder = field.get("placeholder")
        if placeholder is not None and not isinstance(placeholder, str):
            return False, f"Field '{name}': 'placeholder' must be string if provided"

        # choices
        if field_type == "choice":
            choices = field.get("choices")
            if not isinstance(choices, list) or not all(isinstance(c, str) for c in choices):
                return False, f"Field '{name}' of type 'choice' must have a list of string 'choices'"

        # règles spéciales verrouillées
        if field_type == "email" and name != "email":
            return False, f"Field of type 'email' must have name='email'"

    return True, "ok"


def validate_phone_strictly(phone_input: str, default_region: str = "FR") -> Tuple[bool, str, Optional[str]]:
    """
    Valide et normalise un numéro de téléphone avec phonenumbers.
    Args:
        phone_input: numéro saisi par l'utilisateur
        default_region: code pays par défaut (ex: 'FR', 'BJ')
    Returns:
        (is_valid, error_message, formatted_number)
    """
    if not phone_input:
        return False, "Le numéro de téléphone est vide", None

    try:
        parsed_number = phonenumbers.parse(phone_input, default_region)
        if not phonenumbers.is_valid_number(parsed_number):
            return False, "Ce numéro de téléphone n'existe pas ou est invalide.", None
        formatted_number = phonenumbers.format_number(parsed_number, PhoneNumberFormat.E164)
        return True, "", formatted_number
    except NumberParseException:
        return False, "Format de téléphone invalide.", None


def validate_email_strictly(email_input: str) -> Tuple[bool, str, Optional[str]]:
    """
    Valide et normalise un email avec email-validator.
    Args:
        email_input: email saisi par l'utilisateur
    Returns:
        (is_valid, error_message, normalized_email)
    """
    if not email_input:
        return False, "L'email est vide", None

    try:
        check_deliverability = getattr(settings, 'EMAIL_CHECK_DELIVERABILITY', False)
        valid = validate_email(email_input, check_deliverability=check_deliverability)
        return True, "", valid.normalized
    except EmailNotValidError as e:
        return False, str(e), None

def validate_payload_against_schema(payload: Dict[str, Any], schema: Dict[str, Any], default_region: str = "FR") -> Tuple[bool, Dict[str, str], Dict[str, Any]]:
    """
    Valide le payload soumis par le client contre le schéma du formulaire.
    Remplace les emails et téléphones par leurs versions normalisées.
    Ne modifie pas le payload original : renvoie une copie.

    Args:
        payload: données envoyées par le client
        schema: schéma du formulaire (FormSchema.schema)
        default_region: code pays par défaut pour téléphones

    Returns:
        (is_valid: bool, errors: dict, clean_payload: dict)
        errors est un dict vide si valide, sinon { field_name: message }
    """
    fields_def = schema.get('fields', [])
    clean_payload = payload.copy()
    errors: Dict[str, str] = {}

    for field in fields_def:
        field_name = field.get('name')
        field_type = field.get('type')
        is_required = field.get('required', False)

        if is_required and field_name not in clean_payload:
            errors[field_name] = f"Le champ '{field_name}' est obligatoire."
            continue

        if field_name not in clean_payload:
            continue

        value = clean_payload[field_name]

        if value in (None, "") and not is_required:
            clean_payload.pop(field_name, None)
            continue

        if value is None and is_required:
            errors[field_name] = f"Le champ '{field_name}' est obligatoire."
            continue

        if field_type == 'email':
            is_valid, error, normalized = validate_email_strictly(str(value))
            if not is_valid:
                errors[field_name] = f"Email invalide : {error}"
            else:
                clean_payload[field_name] = normalized

        elif field_type == 'phone':
            is_valid, error, normalized = validate_phone_strictly(str(value), default_region)
            if not is_valid:
                errors[field_name] = f"Téléphone invalide : {error}"
            else:
                clean_payload[field_name] = normalized

        elif field_type == 'number':
            try:
                clean_payload[field_name] = float(value)
            except (ValueError, TypeError):
                errors[field_name] = f"Le champ '{field_name}' doit être un nombre."

        elif field_type == 'boolean':
            if not isinstance(value, bool):
                errors[field_name] = f"Le champ '{field_name}' doit être un booléen."

        elif field_type == 'choice':
            choices = field.get('choices', [])
            if value not in choices:
                errors[field_name] = f"Valeur invalide. Choisissez parmi : {', '.join(choices)}."

        elif field_type == 'text':
            if not isinstance(value, str):
                errors[field_name] = f"Le champ '{field_name}' doit être du texte."

        else:
            pass

    if errors:
        return False, errors, clean_payload

    return True, {}, clean_payload
   
if __name__ == "__main__":
    # Exemple d'utilisation
    sample_schema = {
        "fields": [
            {"name": "email", "type": "email", "required": True},
            {"name": "phone", "type": "phone", "required": False},
            {"name": "age", "type": "number", "required": True},
            {"name": "subscribe", "type": "boolean", "required": False},
            {"name": "color", "type": "choice", "choices": ["red", "green", "blue"], "required": True},
        ]
    }   
    sample_payload = {
        "email": "test@gmail.com",
        "phone": "+33612345678",
        "age": 25,
        "subscribe": True,
        "color": "blue"
    }

    # --- Appel patché ---
    is_valid, error, clean_payload = validate_payload_against_schema(sample_payload, sample_schema)
    
    print(f"Validation result: {is_valid}, Error: {error}")
    print("Original payload:", sample_payload)
    print("Clean payload:", clean_payload)
