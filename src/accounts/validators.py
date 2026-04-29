"""
Validators pour l'app accounts.
"""
from rest_framework import serializers


def validate_password_strength(value):
    """
    Valide la force du mot de passe.
    
    Règles:
    - Longueur: 8-15 caractères
    - Au moins 1 majuscule
    - Au moins 1 minuscule
    - Au moins 1 chiffre
    """
    if len(value) < 8:
        raise serializers.ValidationError("Le mot de passe doit contenir au moins 8 caractères.")
    
    if len(value) > 15:
        raise serializers.ValidationError("Le mot de passe ne doit pas dépasser 15 caractères.")
    
    if not any(c.isupper() for c in value):
        raise serializers.ValidationError("Le mot de passe doit contenir au moins une majuscule.")
    
    if not any(c.islower() for c in value):
        raise serializers.ValidationError("Le mot de passe doit contenir au moins une minuscule.")
    
    if not any(c.isdigit() for c in value):
        raise serializers.ValidationError("Le mot de passe doit contenir au moins un chiffre.")
    
    return value
