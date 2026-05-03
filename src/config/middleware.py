import re
from django.conf import settings
from django.http import HttpResponse


class HybridCORSMiddleware:
    """
    Politique CORS hybride à deux vitesses :

    1. /api/v1/portal/ → ouvert à toutes les origines (widget public embarqué
       sur n'importe quel site client). On reflète l'Origin exacte plutôt que '*'
       parce qu'on envoie credentials: true, et le navigateur interdit '*' dans ce cas.

    2. Tous les autres endpoints → liste blanche stricte via CORS_ALLOWED_ORIGINS.
       Seules les origines explicitement listées reçoivent les headers CORS.

    Note : quand il n'y a pas d'header Origin (Postman, curl, appels serveur-à-serveur),
    on laisse toujours passer. CORS est un contrat navigateur ↔ serveur, pas un système
    d'authentification. La vraie protection des données, c'est le JWT géré par DRF.

    Ce middleware doit être placé EN PREMIER dans MIDDLEWARE (avant tout autre),
    et remplace complètement corsheaders.middleware.CorsMiddleware.
    """

    PORTAL_REGEX = re.compile(r'^/api/v1/portal/')

    ALLOWED_HEADERS = 'Content-Type, Authorization, X-Requested-With'
    ALLOWED_METHODS = 'GET, POST, PUT, PATCH, DELETE, OPTIONS'
    CORS_MAX_AGE = '86400'  # Le navigateur met le résultat du préflight en cache 24h

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        origin = request.META.get('HTTP_ORIGIN')

        # ----------------------------------------------------------------
        # CAS 1 : endpoint portal — widget public, tout le monde est autorisé
        # ----------------------------------------------------------------
        if self.PORTAL_REGEX.match(request.path_info):

            # Préflight OPTIONS : le navigateur demande la permission avant
            # d'envoyer la vraie requête. On répond immédiatement sans passer
            # par Django (pas besoin d'authentification pour ce check).
            if request.method == 'OPTIONS':
                response = HttpResponse()
                self._set_portal_cors_headers(response, origin)
                return response

            # Requête normale : on laisse Django traiter, puis on colle les headers
            response = self.get_response(request)
            self._set_portal_cors_headers(response, origin)
            return response

        # ----------------------------------------------------------------
        # CAS 2 : tous les autres endpoints — liste blanche stricte
        # ----------------------------------------------------------------
        if request.method == 'OPTIONS':
            # Préflight : vérifier l'origine AVANT de laisser passer
            if self._is_origin_allowed(origin):
                response = HttpResponse()
                self._set_private_cors_headers(response, origin)
                return response
            else:
                # Origine non autorisée → on refuse le préflight proprement
                return HttpResponse(status=403)

        # Requête normale : Django traite, on ajoute les headers seulement si autorisé
        response = self.get_response(request)
        if self._is_origin_allowed(origin):
            self._set_private_cors_headers(response, origin)

        return response

    # ----------------------------------------------------------------
    # Helpers
    # ----------------------------------------------------------------

    def _is_origin_allowed(self, origin):
        """
        Vérifie si l'origine est autorisée à accéder aux endpoints privés.

        Trois cas possibles :
        - Pas d'Origin du tout → requête non-navigateur (Postman, curl...) → on laisse passer.
        - DEBUG = True → environnement de développement → on laisse tout passer
          sans avoir à maintenir une liste dans dev.py.
        - Sinon → on vérifie que l'origine est bien dans CORS_ALLOWED_ORIGINS (prod).
        """
        if not origin:
            return True

        # En mode DEBUG (dev), on ne bloque rien pour ne pas gêner le développement.
        # En prod, DEBUG = False, donc cette ligne est sans effet.
        if getattr(settings, 'DEBUG', False):
            return True

        allowed = getattr(settings, 'CORS_ALLOWED_ORIGINS', [])
        return origin in allowed

    def _set_portal_cors_headers(self, response, origin):
        """
        Headers pour le portail public : toutes les origines sont les bienvenues.
        On utilise l'origine reflétée (et non '*') car credentials = true.
        """
        response['Access-Control-Allow-Origin'] = origin or '*'
        response['Access-Control-Allow-Credentials'] = 'true'
        response['Access-Control-Allow-Methods'] = self.ALLOWED_METHODS
        response['Access-Control-Allow-Headers'] = self.ALLOWED_HEADERS
        response['Access-Control-Max-Age'] = self.CORS_MAX_AGE

    def _set_private_cors_headers(self, response, origin):
        """
        Headers pour les endpoints privés : origine déjà vérifiée par _is_origin_allowed.
        """
        response['Access-Control-Allow-Origin'] = origin
        response['Access-Control-Allow-Credentials'] = 'true'
        response['Access-Control-Allow-Methods'] = self.ALLOWED_METHODS
        response['Access-Control-Allow-Headers'] = self.ALLOWED_HEADERS
        response['Access-Control-Max-Age'] = self.CORS_MAX_AGE
