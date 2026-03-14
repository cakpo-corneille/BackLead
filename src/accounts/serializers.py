"""
Serializers pour l'app accounts avec support du code OTP.
"""
from django.db import transaction 
from rest_framework import serializers
from django.contrib.auth import authenticate, get_user_model
from .models import OwnerProfile
from .validators import validate_password_strength

User = get_user_model()


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ('id', 'email', 'is_verify')


class RegisterSerializer(serializers.Serializer):
    """Serializer pour l'inscription."""
    
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, min_length=8, max_length=15)
    
    def validate_email(self, value):
        """Vérifier l'unicité de l'email."""
        email = value.lower().strip()
        
        if User.objects.filter(email=email).exists():
            raise serializers.ValidationError('Cet email est déjà utilisé.')
        
        return email
    
    def validate_password(self, value):
        """Valider la force du mot de passe."""
        return validate_password_strength(value)
    
    def create(self, validated_data):
        """Créer l'utilisateur de manière atomique."""
        email = validated_data['email'].lower().strip()
        password = validated_data['password']
        
        with transaction.atomic():
            user = User.objects.create_user(
                email=email,
                password=password
            )
        
        # Le signal post_save créera automatiquement le OwnerProfile
        
        return user


class VerifyCodeSerializer(serializers.Serializer):
    """Serializer pour la vérification du code à 6 chiffres."""
    
    user_id = serializers.IntegerField()
    code = serializers.CharField(min_length=6, max_length=6)
    
    def validate_code(self, value):
        """Vérifier que le code ne contient que des chiffres."""
        if not value.isdigit():
            raise serializers.ValidationError('Le code doit contenir uniquement des chiffres.')
        
        return value


class LoginSerializer(serializers.Serializer):
    """Serializer pour la connexion."""
    
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)
    
    def validate(self, attrs):
        """Valider les identifiants."""
        email = attrs.get('email', '').lower().strip()
        password = attrs.get('password', '')
        
        user = authenticate(username=email, password=password)
        
        if not user:
            raise serializers.ValidationError('Email ou mot de passe incorrect.')
        
        attrs['user'] = user
        return attrs


class ForgotPasswordSerializer(serializers.Serializer):
    """Serializer pour demander un code de réinitialisation."""
    email = serializers.EmailField()


class ResetPasswordSerializer(serializers.Serializer):
    """Serializer pour réinitialiser le mot de passe."""
    user_id = serializers.IntegerField()
    code = serializers.CharField(min_length=6, max_length=6)
    new_password = serializers.CharField(write_only=True, min_length=8, max_length=15)
    
    def validate_code(self, value):
        if not value.isdigit():
            raise serializers.ValidationError('Le code doit contenir uniquement des chiffres.')
        return value
    
    def validate_new_password(self, value):
        return validate_password_strength(value)


class ChangePasswordSerializer(serializers.Serializer):
    """Serializer pour changer le mot de passe."""
    old_password = serializers.CharField(write_only=True)
    new_password = serializers.CharField(write_only=True, min_length=8, max_length=15)
    
    def validate_new_password(self, value):
        return validate_password_strength(value)

        

class OwnerProfileSerializer(serializers.ModelSerializer):
    """Serializer pour le profil propriétaire."""

    user = UserSerializer(read_only=True)  
    logo_url = serializers.SerializerMethodField(read_only=True)
    
    class Meta:
        model = OwnerProfile
        fields = (
            'user',
            'business_name',
            'logo',
            'logo_url',
            'nom',
            'prenom',
            'phone_contact',
            'whatsapp_contact',
            'pays',
            'ville',
            'quartier',
            'main_goal',
            'is_complete',
        )
        read_only_fields = ('user', 'is_complete')
    
    def get_logo_url(self, obj):
        """Retourner l'URL complète et présignée du logo."""
        if obj.logo:
            return obj.logo.url
        return None
    
    def validate_logo(self, value):
        """Valider le logo uploadé."""
        if value:
            # Taille maximale : 2MB
            if value.size > 2 * 1024 * 1024:
                raise serializers.ValidationError('Le logo ne doit pas dépasser 2MB.')
            
            # Formats autorisés
            allowed_types = ['image/jpeg', 'image/png', 'image/jpg', 'image/webp']
            if value.content_type not in allowed_types:
                raise serializers.ValidationError(
                    'Format non supporté. Utilisez JPEG, PNG ou WebP.'
                )
        
        return value
