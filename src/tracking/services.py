# tracking/services.py
import logging
from django.utils import timezone
from .models import ConnectionSession, TicketPlan

logger = logging.getLogger(__name__)


def match_ticket_plan(owner, session_timeout_seconds):
    """
    Identifie le TicketPlan dont la durée correspond exactement à session_timeout.
    Ex: session_timeout = 14400s (4h) → plan 240 min → trouvé.
    Aucune correspondance exacte → None.
    """
    if not session_timeout_seconds or session_timeout_seconds <= 0:
        return None

    for plan in TicketPlan.objects.filter(owner=owner, is_active=True):
        if plan.duration_minutes * 60 == session_timeout_seconds:
            return plan

    return None


def close_session(session_key):
    """Ferme une session par sa clé (utilisé en admin ou tests)."""
    return ConnectionSession.objects.filter(
        session_key=session_key,
        is_active=True,
    ).update(is_active=False, ended_at=timezone.now())
