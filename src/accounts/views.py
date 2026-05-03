"""
Views pour l'authentification et la gestion des profils avec code OTP.
"""
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from rest_framework_simplejwt.tokens import RefreshToken
from django.contrib.auth import authenticate
import logging

from .models import OwnerProfile
from .serializers import (
    ChangePasswordSerializer,
    ForgotPasswordSerializer,
    RegisterSerializer,
    LoginSerializer,
    OwnerProfileSerializer,
    ResetPasswordSerializer,
    VerifyCodeSerializer,
    ChangeEmailSerializer,
)
from .services import (
    send_verification_code,
    verify_code,
    resend_verification_code,
    check_profile_completion,
    send_change_email_code,
)
from .tasks import send_verification_code_task

logger = logging.getLogger(__name__)


def get_tokens_for_user(user):
    """Génère les tokens JWT pour un utilisateur."""
    refresh = RefreshToken.for_user(user)
    return {
        'refresh': str(refresh),
        'access': str(refresh.access_token),
    }


class AuthViewSet(viewsets.ViewSet):
    """ViewSet pour l'authentification (register, login, verify, logout)."""
    
    permission_classes = [AllowAny]
    
    @action(detail=False, methods=['post'])
    def register(self, request):
        """
        Inscription d'un nouvel utilisateur.
        
        Envoie un code de vérification par email.
        L'utilisateur doit ensuite appeler /verify/ avec le code.
        """
        serializer = RegisterSerializer(data=request.data)
        
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        
        user = serializer.save()
        
        # Double Sécurité Email : Tentative Celery, puis direct en cas d'échec
        try:
            # On tente d'abord l'envoi asynchrone (Celery)
            send_verification_code_task.delay(user.id)
            
            response_data = {
                'ok': True,
                'message': 'Compte créé. Un code de vérification a été envoyé à votre email.',
                'user_id': user.id,
                'email': user.email,
            }
            
            if request.query_params.get('debug') == 'true':
                response_data['debug_mode'] = 'Celery task triggered'
                
            return Response(response_data, status=status.HTTP_201_CREATED)
            
        except Exception as celery_e:
            logger.warning(f"Celery failed, trying direct send: {str(celery_e)}")
            
            # Si Celery échoue, on tente l'envoi en direct
            try:
                send_verification_code(user)
                
                response_data = {
                    'ok': True,
                    'message': 'Compte créé. Un code de vérification a été envoyé à votre email.',
                    'user_id': user.id,
                    'email': user.email,
                }
                
                return Response(response_data, status=status.HTTP_201_CREATED)
                
            except Exception as e:
                # Intégrité : Si même l'envoi direct échoue, on supprime l'utilisateur
                user.delete()
                return Response(
                    {'error': f'Erreur lors de l\'envoi de l\'email: {str(e)}'},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )
    
    @action(detail=False, methods=['post'])
    def verify(self, request):
        """
        Vérification du code à 6 chiffres.
        
        Si le code est valide, retourne les tokens JWT.
        """
        serializer = VerifyCodeSerializer(data=request.data)
        
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        
        user_id = serializer.validated_data['user_id']
        code = serializer.validated_data['code']
        
        from django.contrib.auth import get_user_model
        User = get_user_model()
        
        try:
            user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            return Response(
                {'error': 'Utilisateur introuvable.'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Vérifier le code (met is_verify = True si valide)
        success, error_message = verify_code(user, code)
        
        if not success:
            return Response({'error': error_message}, status=status.HTTP_400_BAD_REQUEST)
        
        # Code valide → Générer les tokens JWT
        tokens = get_tokens_for_user(user)
        
        # Vérifier l'état du profil
        profile_status = check_profile_completion(user)
        
        return Response({
            'ok': True,
            'access': tokens['access'],
            'refresh': tokens['refresh'],
            'user': {
                'id': user.id,
                'email': user.email,
                'is_verify': user.is_verify,
            },
            'profile_status': profile_status,
            'redirect': '/onboarding' if not profile_status['is_complete'] else '/dashboard',
        }, status=status.HTTP_200_OK)
    
    @action(detail=False, methods=['post'])
    def resend_code(self, request):
        """
        Renvoie un nouveau code de vérification.
        
        Rate limit: 1 code par minute.
        """
        user_id = request.data.get('user_id')
        
        if not user_id:
            return Response(
                {'error': 'user_id est requis.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        from django.contrib.auth import get_user_model
        User = get_user_model()
        
        try:
            user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            return Response(
                {'error': 'Utilisateur introuvable.'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        success, message = resend_verification_code(user)
        
        if not success:
            return Response({'error': message}, status=status.HTTP_429_TOO_MANY_REQUESTS)
        
        return Response({'ok': True, 'message': message}, status=status.HTTP_200_OK)
    
    @action(detail=False, methods=['post'])
    def login(self, request):
        """
        Connexion d'un utilisateur existant.
        
        Retourne directement les tokens JWT si les identifiants sont valides.
        Bloque si email non vérifié.
        """
        serializer = LoginSerializer(data=request.data)
        
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        
        user = serializer.validated_data['user']
        
        # Vérifier si email vérifié
        if not user.is_verify:
            return Response({
                'ok': False,
                'error': 'Email non vérifié. Veuillez vérifier votre boîte mail.',
                'redirect': '/verify-email',
                'user_id': user.id
            }, status=status.HTTP_403_FORBIDDEN)
        
        tokens = get_tokens_for_user(user)
        
        # Vérifier l'état du profil
        profile_status = check_profile_completion(user)
        
        return Response({
            'ok': True,
            'access': tokens['access'],
            'refresh': tokens['refresh'],
            'user': {
                'id': user.id,
                'email': user.email,
                'is_verify': user.is_verify,
            },
            'profile_status': profile_status,
            'redirect': '/onboarding' if not profile_status['is_complete'] else '/dashboard',
        }, status=status.HTTP_200_OK)
    

    @action(detail=False, methods=['post'])
    def forgot_password(self, request):
        """
        Demande de réinitialisation de mot de passe.
        Envoie un code par email.
        """
        serializer = ForgotPasswordSerializer(data=request.data)
        
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        
        email = serializer.validated_data['email']
        
        from .services import send_password_reset_code
        success, user_or_message = send_password_reset_code(email)
        
        if not success:
            return Response(
                {'error': user_or_message},
                status=status.HTTP_404_NOT_FOUND
            )
        
        return Response({
            'ok': True,
            'message': 'Un code de réinitialisation a été envoyé à votre email.',
            'user_id': user_or_message.id
        }, status=status.HTTP_200_OK)


    @action(detail=False, methods=['post'])
    def reset_password(self, request):
        """
        Réinitialise le mot de passe avec le code reçu.
        """
        serializer = ResetPasswordSerializer(data=request.data)
        
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        
        user_id = serializer.validated_data['user_id']
        code = serializer.validated_data['code']
        new_password = serializer.validated_data['new_password']
        
        from .services import reset_password_with_code
        success, error_message = reset_password_with_code(user_id, code, new_password)
        
        if not success:
            return Response(
                {'error': error_message},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        return Response({
            'ok': True,
            'message': 'Mot de passe réinitialisé avec succès.'
        }, status=status.HTTP_200_OK)


    @action(detail=False, methods=['post'], permission_classes=[IsAuthenticated])
    def logout(self, request):
        """
        Déconnexion (endpoint symbolique, JWT étant stateless).
        """
        return Response({'ok': True}, status=status.HTTP_200_OK)


class ProfileViewSet(viewsets.ViewSet):
    """ViewSet pour la gestion du profil utilisateur."""
    
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    
    @action(detail=False, methods=['get', 'put', 'patch'])
    def me(self, request):
        """
        GET: Récupérer le profil de l'utilisateur connecté.
        PUT/PATCH: Mettre à jour le profil.
        """
        user = request.user
        profile = user.profile
        
        if request.method == 'GET':
            serializer = OwnerProfileSerializer(profile, context={'request': request})
            
            # Ajouter le statut de complétion
            profile_status = check_profile_completion(user)
            
            return Response({
                'user': {
                    'id': user.id,
                    'email': user.email,
                    'is_verify': user.is_verify,
                },
                'profile': serializer.data,
                'profile_status': profile_status,
            })
        
        elif request.method in ['PUT', 'PATCH']:
            partial = request.method == 'PATCH'
            serializer = OwnerProfileSerializer(
                profile,
                data=request.data,
                partial=partial,
                context={'request': request}
            )
            
            if not serializer.is_valid():
                return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
            
            serializer.save()  # Déclenche le calcul automatique de is_complete
            
            # Recalculer le statut de complétion
            profile_status = check_profile_completion(user)
            
            return Response({
                'ok': True,
                'profile': serializer.data,
                'profile_status': profile_status,
                'redirect': '/dashboard' if profile_status['is_complete'] else '/onboarding',
            })
    
    @action(detail=False, methods=['get'])
    def status(self, request):
        """
        Retourne l'état de complétion du profil.
        
        Utile pour le frontend pour décider s'il faut afficher l'onboarding.
        """
        user = request.user
        profile_status = check_profile_completion(user)
        
        return Response(profile_status)

    @action(detail=False, methods=['post'])
    def change_password(self, request):
        """
        Change le mot de passe de l'utilisateur connecté.
        """
        serializer = ChangePasswordSerializer(data=request.data)
        
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        
        old_password = serializer.validated_data['old_password']
        new_password = serializer.validated_data['new_password']
        
        from .services import change_password
        success, error_message = change_password(request.user, old_password, new_password)
        
        if not success:
            return Response(
                {'error': error_message},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        return Response({
            'ok': True,
            'message': 'Mot de passe modifié avec succès.'
        }, status=status.HTTP_200_OK)

    @action(detail=False, methods=['post'])
    def change_email(self, request):
        """
        Initie un changement d'email pour l'utilisateur connecté.
        Envoie un code de vérification au nouvel email.
        """
        serializer = ChangeEmailSerializer(data=request.data)
        
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        
        new_email = serializer.validated_data['new_email']
        
        # Envoyer le code au NOUVEL email
        send_change_email_code(request.user, new_email)
        
        return Response({
            'ok': True,
            'message': f'Un code de confirmation a été envoyé à {new_email}.'
        }, status=status.HTTP_200_OK)