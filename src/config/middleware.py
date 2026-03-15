import re
from django.http import HttpResponse

class HybridCORSMiddleware:
    """
    Implements a hybrid CORS policy based on the request path.

    This middleware must be placed BEFORE 'corsheaders.middleware.CorsMiddleware'
    in the MIDDLEWARE setting.

    - For paths matching the portal API regex (`/api/v1/portal/`), it dynamically
      reflects the request's `Origin` header and allows credentials. This is
      necessary because the widget sends credentials (`credentials: 'include'`) and
      the browser forbids using a wildcard `*` for the origin in this case.
      
    - It specifically handles preflight OPTIONS requests for the portal API to ensure
      they are not blocked by the more restrictive default CORS policy.

    - For all other paths, it does nothing, letting the next middleware in the chain
      (e.g., django-cors-headers) apply its configured policy.
    """
    PORTAL_REGEX = re.compile(r'^/api/v1/portal/')

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        origin = request.META.get('HTTP_ORIGIN')

        # Handle preflight OPTIONS requests for the portal API.
        # This needs to run before CorsMiddleware.
        if request.method == 'OPTIONS' and self.PORTAL_REGEX.match(request.path_info):
            response = HttpResponse()
            if origin:
                response['Access-Control-Allow-Origin'] = origin
            
            response['Access-Control-Allow-Credentials'] = 'true'
            response['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
            response['Access-Control-Allow-Headers'] = 'Content-Type, Authorization'
            response['Access-Control-Max-Age'] = '86400'  # 1 day
            return response

        # For all other requests, get the response from the next middleware.
        response = self.get_response(request)

        # For non-preflight requests on the portal API path, modify the response
        # to reflect the origin and allow credentials.
        if self.PORTAL_REGEX.match(request.path_info):
            if origin:
                response['Access-Control-Allow-Origin'] = origin
            
            response['Access-Control-Allow-Credentials'] = 'true'
            # We are explicitly setting credentials to true, so no need to delete it.
            # This will override any value set by `corsheaders` middleware.

        return response
