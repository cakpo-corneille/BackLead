from rest_framework import permissions


class IsSuperAdmin(permissions.BasePermission):
    """
    Permission qui n'autorise que les superadmins.
    Un superadmin est un User avec is_superuser=True.
    """
    message = "Acces reserve aux super administrateurs."
    
    def has_permission(self, request, view):
        return bool(
            request.user and
            request.user.is_authenticated and
            request.user.is_superuser
        )


class IsSuperAdminOrReadOnly(permissions.BasePermission):
    """
    Permission qui autorise la lecture a tous les admins staff,
    mais restreint les modifications aux superadmins.
    """
    message = "Modification reservee aux super administrateurs."
    
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        
        # Lecture autorisee pour staff
        if request.method in permissions.SAFE_METHODS:
            return request.user.is_staff
        
        # Ecriture reservee aux superadmins
        return request.user.is_superuser


class CanImpersonate(permissions.BasePermission):
    """
    Permission speciale pour l'impersonation.
    Necessite is_superuser ET une verification supplementaire.
    """
    message = "L'impersonation necessite des droits superadmin."
    
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        
        # Doit etre superuser
        if not request.user.is_superuser:
            return False
        
        # Verification supplementaire: ne peut pas s'auto-impersonner
        # (sera verifie dans la vue avec l'owner cible)
        return True
    
    def has_object_permission(self, request, view, obj):
        # Ne peut pas impersonner un autre superadmin
        if hasattr(obj, 'user') and obj.user.is_superuser:
            return False
        return True
