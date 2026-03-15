import re
from django.http import HttpResponse

class HybridCORSMiddleware:
    """
    Implements a hybrid CORS policy based on the request path.

    This middleware must be placed BEFORE 'corsheaders.middleware.CorsMiddleware'
    in the MIDDLEWARE setting.

    - For paths matching the portal API regex (`/api/v1/portal/`), it applies an open
      policy (all origins allowed, no credentials).
    - It specifically handles preflight OPTIONS requests for the portal API to ensure
      they are not blocked by the more restrictive default CORS policy.
    - For all other paths, it does nothing, letting the next middleware in the chain
      (e.g., django-cors-headers) apply its configured policy.
    """
    PORTAL_REGEX = re.compile(r'^/api/v1/portal/')

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Handle preflight OPTIONS requests for the portal API.
        # This needs to run before CorsMiddleware, which would otherwise
        # short-circuit the request with a more restrictive policy.
        if request.method == 'OPTIONS' and self.PORTAL_REGEX.match(request.path_info):
            response = HttpResponse()
            response['Access-Control-Allow-Origin'] = '*'
            response['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
            response['Access-Control-Allow-Headers'] = 'Content-Type, Authorization'
            response['Access-Control-Max-Age'] = '86400' # 1 day
            return response

        # For all other requests, get the response from the next middleware.
        response = self.get_response(request)

        # For non-preflight requests on the portal API path, modify the response.
        if self.PORTAL_REGEX.match(request.path_info):
            # Set a public origin.
            response['Access-Control-Allow-Origin'] = '*'

            # When the origin is a wildcard '*' or a list of origins, credentials cannot be supported.
            # CorsMiddleware might have set this header to 'true', so we ensure
            # it is removed for these specific public paths.
            if 'Access-Control-Allow-Credentials' in response:
                del response['Access-Control-Allow-Credentials']

        return response
