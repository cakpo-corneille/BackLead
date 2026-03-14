import re

class HybridCORSMiddleware:
    """
    Implements a hybrid CORS policy based on the request path.

    - For paths matching the portal API regex, it applies an open policy (all origins allowed).
    - For all other paths, it lets the default django-cors-headers middleware apply its
      configured policy (e.g., the whitelist).

    This middleware MUST be placed *after* 'corsheaders.middleware.CorsMiddleware'
    in the MIDDLEWARE setting.
    """
    PORTAL_REGEX = re.compile(r'^/api/v1/portal/')

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Let the default middleware chain run and get the response.
        response = self.get_response(request)

        # Check if the path is for the public portal API.
        if self.PORTAL_REGEX.match(request.path_info):
            # Override the origin to be public.
            response['Access-Control-Allow-Origin'] = '*'
            
            # When the origin is a wildcard '*', credentials cannot be supported.
            # The default CorsMiddleware might have set this to 'true' based on
            # settings, so we must remove it for these specific public paths.
            if 'Access-Control-Allow-Credentials' in response:
                del response['Access-control-allow-credentials']

        return response
