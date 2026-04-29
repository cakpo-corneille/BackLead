from django.utils import timezone
from django.http import JsonResponse
from django.conf import settings
from django.db import connection
from django.core.cache import cache
import logging

logger = logging.getLogger(__name__)


def healthcheck(request):
    """Health check complet pour monitoring externe."""
    status_code = 200
    health_data = {
        "status": "healthy",
        "timestamp": timezone.now().isoformat(),
        "environment": "production" if not settings.DEBUG else "development",
        "checks": {}
    }
    
    # Database
    try:
        connection.ensure_connection()
        health_data["checks"]["database"] = "OK"
    except Exception as e:
        health_data["checks"]["database"] = f"FAIL: {str(e)}"
        health_data["status"] = "unhealthy"
        status_code = 503

    # Cache (Redis)
    try:
        cache.set('healthcheck_test', 'ok', 5)
        if cache.get('healthcheck_test') == 'ok':
            health_data["checks"]["cache"] = "OK"
        else:
            raise Exception("Cache mismatch")
    except Exception as e:
        health_data["checks"]["cache"] = f"FAIL: {str(e)}"
        health_data["status"] = "unhealthy"
        status_code = 503

    # Celery (non-bloquant)
    try:
        from celery import current_app
        insp = current_app.control.inspect()
        stats = insp.stats()
        if stats:
            health_data["checks"]["celery"] = "OK"
        else:
            health_data["checks"]["celery"] = "WARN: No active workers"
    except Exception as e:
        health_data["checks"]["celery"] = f"WARN: {str(e)}"

    return JsonResponse(health_data, status=status_code)


def readiness(request):
    """Readiness probe pour Kubernetes."""
    try:
        connection.ensure_connection()
        from django.apps import apps
        if not apps.ready:
            raise Exception("Apps not ready")
        return JsonResponse({"status": "ready"}, status=200)
    except Exception as e:
        logger.error(f"Readiness failed: {e}")
        return JsonResponse({"status": "not ready", "reason": str(e)}, status=503)


def liveness(request):
    """Liveness probe pour Kubernetes."""
    return JsonResponse({"status": "alive"}, status=200)