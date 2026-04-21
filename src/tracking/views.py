# tracking/views.py
from datetime import timedelta

from django.db.models import Sum, Avg, Count, F, Q
from django.utils import timezone
from django.utils.decorators import method_decorator

from rest_framework import viewsets, status, mixins
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from core_data.decorators import ratelimit_public_api

from .models import TicketPlan, ConnectionSession
from .serializers import (
    HeartbeatSerializer,
    EndSessionSerializer,
    TicketPlanSerializer,
    ConnectionSessionSerializer,
)
from .services import handle_heartbeat, close_session


# ============================================================
# Endpoints PUBLICS (tracker.js sur status.html / logout.html)
# ============================================================

class TrackingViewSet(viewsets.ViewSet):
    permission_classes = [AllowAny]

    @method_decorator(ratelimit_public_api(requests=30, duration=60))
    @action(detail=False, methods=['post'])
    def heartbeat(self, request):
        """
        Reçoit les données de session de tracker.js.
        Appelé à chaque refresh de status.html par MikroTik.
        """
        serializer = HeartbeatSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        try:
            session, created = handle_heartbeat(serializer.validated_data)
            return Response(
                {
                    'ok': True,
                    'session_key': str(session.session_key),
                    'created': created,
                },
                status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
            )
        except ValueError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception:
            # Ne jamais renvoyer 500 au tracker : on log silencieusement
            return Response({'ok': False}, status=status.HTTP_200_OK)

    @action(detail=False, methods=['post'])
    def end(self, request):
        """
        Ferme une session. Appelé par tracker.js sur logout.html
        via navigator.sendBeacon() (survit à la navigation).
        """
        serializer = EndSessionSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        closed = close_session(str(serializer.validated_data['session_key']))
        return Response({'ok': True, 'closed': closed})


# ============================================================
# Endpoints DASHBOARD OWNER (authentifiés)
# ============================================================

class TicketPlanViewSet(viewsets.ModelViewSet):
    """CRUD complet sur les plans tarifaires de l'owner connecté."""
    serializer_class = TicketPlanSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return TicketPlan.objects.filter(owner=self.request.user)

    def perform_create(self, serializer):
        serializer.save(owner=self.request.user)


class SessionAnalyticsViewSet(viewsets.ViewSet):
    """
    Analytics des sessions WiFi pour le dashboard owner.
    Données live (pas de cache long, on veut la fraîcheur).
    """
    permission_classes = [IsAuthenticated]

    def _base_qs(self):
        return ConnectionSession.objects.filter(owner=self.request.user)

    @action(detail=False, methods=['get'])
    def overview(self, request):
        """Vue d'ensemble pour le dashboard."""
        qs = self._base_qs()
        now = timezone.now()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        week_start = today_start - timedelta(days=7)
        month_start = today_start - timedelta(days=30)

        agg = qs.aggregate(
            total_sessions=Count('id'),
            total_bytes=Sum(F('bytes_downloaded') + F('bytes_uploaded')),
            avg_uptime=Avg('uptime_seconds'),
        )
        revenue_today = qs.filter(
            started_at__gte=today_start, ticket_plan__isnull=False
        ).aggregate(total=Sum('ticket_plan__price_fcfa'))['total'] or 0
        revenue_week = qs.filter(
            started_at__gte=week_start, ticket_plan__isnull=False
        ).aggregate(total=Sum('ticket_plan__price_fcfa'))['total'] or 0
        revenue_month = qs.filter(
            started_at__gte=month_start, ticket_plan__isnull=False
        ).aggregate(total=Sum('ticket_plan__price_fcfa'))['total'] or 0

        return Response({
            'total_sessions': agg['total_sessions'] or 0,
            'sessions_today': qs.filter(started_at__gte=today_start).count(),
            'sessions_this_week': qs.filter(started_at__gte=week_start).count(),
            'sessions_this_month': qs.filter(started_at__gte=month_start).count(),
            'active_sessions': qs.filter(is_active=True).count(),
            'avg_session_seconds': int(agg['avg_uptime'] or 0),
            'total_mb': round((agg['total_bytes'] or 0) / (1024 ** 2), 2),
            'estimated_revenue_today_fcfa': revenue_today,
            'estimated_revenue_week_fcfa': revenue_week,
            'estimated_revenue_month_fcfa': revenue_month,
        })

    @action(detail=False, methods=['get'], url_path='by-day')
    def by_day(self, request):
        """Sessions par jour sur les N derniers jours (défaut 30)."""
        try:
            days = max(1, min(int(request.query_params.get('days', 30)), 90))
        except (TypeError, ValueError):
            days = 30
        cutoff = timezone.now() - timedelta(days=days)

        from django.db.models.functions import TruncDate
        rows = (
            self._base_qs()
            .filter(started_at__gte=cutoff)
            .annotate(day=TruncDate('started_at'))
            .values('day')
            .annotate(count=Count('id'))
            .order_by('day')
        )
        return Response({
            'labels': [r['day'].isoformat() for r in rows],
            'data':   [r['count'] for r in rows],
        })

    @action(detail=False, methods=['get'], url_path='by-hour')
    def by_hour(self, request):
        """Répartition des sessions par heure de la journée (heures de pointe)."""
        from django.db.models.functions import ExtractHour
        rows = (
            self._base_qs()
            .annotate(hour=ExtractHour('started_at'))
            .values('hour')
            .annotate(count=Count('id'))
            .order_by('hour')
        )
        buckets = {r['hour']: r['count'] for r in rows}
        return Response({
            'labels': list(range(24)),
            'data':   [buckets.get(h, 0) for h in range(24)],
        })

    @action(detail=False, methods=['get'], url_path='top-clients')
    def top_clients(self, request):
        """Top 10 des clients les plus actifs (par nb de sessions)."""
        rows = (
            self._base_qs()
            .values('client_id', 'client__email', 'client__phone', 'client__mac_address')
            .annotate(
                sessions_count=Count('id'),
                total_seconds=Sum('uptime_seconds'),
                total_bytes=Sum(F('bytes_downloaded') + F('bytes_uploaded')),
            )
            .order_by('-sessions_count')[:10]
        )
        return Response([
            {
                'client_id': r['client_id'],
                'email': r['client__email'],
                'phone': r['client__phone'],
                'mac_address': r['client__mac_address'],
                'sessions_count': r['sessions_count'],
                'total_seconds': r['total_seconds'] or 0,
                'total_mb': round((r['total_bytes'] or 0) / (1024 ** 2), 2),
            }
            for r in rows
        ])


class ConnectionSessionViewSet(mixins.ListModelMixin,
                               mixins.RetrieveModelMixin,
                               viewsets.GenericViewSet):
    """Historique des sessions de l'owner connecté (lecture seule)."""
    serializer_class = ConnectionSessionSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = ConnectionSession.objects.filter(owner=self.request.user) \
            .select_related('client', 'ticket_plan')

        # Filtres simples
        is_active = self.request.query_params.get('is_active')
        if is_active is not None:
            qs = qs.filter(is_active=is_active.lower() in ('true', '1'))

        client_id = self.request.query_params.get('client')
        if client_id:
            qs = qs.filter(client_id=client_id)

        date_from = self.request.query_params.get('date_from')
        if date_from:
            qs = qs.filter(started_at__date__gte=date_from)

        date_to = self.request.query_params.get('date_to')
        if date_to:
            qs = qs.filter(started_at__date__lte=date_to)

        return qs
