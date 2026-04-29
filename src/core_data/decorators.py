from django.core.cache import cache
from rest_framework.response import Response
from rest_framework import status
from functools import wraps


def ratelimit_public_api(requests=5, duration=60):
    """
    Rate limiting par IP avec increment atomique (Redis).
    """
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view(request, *args, **kwargs):
            # Récupération IP (gère les proxies)
            x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
            if x_forwarded_for:
                ip = x_forwarded_for.split(',')[0].strip()
            else:
                ip = request.META.get('REMOTE_ADDR', 'unknown')

            key = f"ratelimit_{view_func.__name__}_{ip}"

            try:
                # Increment atomique
                current = cache.incr(key)
            except ValueError:
                # Clé n'existe pas encore, on la crée
                cache.set(key, 1, duration)
                current = 1

            if current > requests:
                return Response(
                    {"error": "Too many requests. Try again later."},
                    status=status.HTTP_429_TOO_MANY_REQUESTS,
                )

            return view_func(request, *args, **kwargs)
        return _wrapped_view
    return decorator