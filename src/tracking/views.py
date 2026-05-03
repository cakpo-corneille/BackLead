# tracking/views.py
from datetime import timedelta

from django.db.models import Sum, Avg, Count, F
from django.utils import timezone

from rest_framework import viewsets, status, mixins
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import TicketPlan, ConnectionSession
from .serializers import (
    HotspotLoginSerializer,
    HotspotLogoutSerializer,
    TicketPlanSerializer,
    ConnectionSessionSerializer,
)
from .hotspot_service import validate_owner_key, handle_login, handle_logout


# ============================================================
# Endpoints Hotspot MikroTik (scripts on-login / on-logout)
# ============================================================

class HotspotLoginView(APIView):
    """
    POST /api/v1/sessions/login/

    Appelé par le script on-login du routeur MikroTik.
    Authentification via owner_key (public_key du FormSchema).
    Objectif : répondre en < 500ms — pas de traitement lourd ici.
    """
    authentication_classes = []  # Pas de JWT — le routeur s'authentifie via owner_key
    permission_classes = [AllowAny]
    throttle_scope = 'hotspot'

    def post(self, request):
        serializer = HotspotLoginSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        data = serializer.validated_data
        try:
            owner = validate_owner_key(str(data['owner_key']))
        except ValueError as e:
            return Response({'detail': str(e)}, status=status.HTTP_401_UNAUTHORIZED)

        try:
            session = handle_login(owner, data)
        except Exception as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        if session is None:
            # Client inconnu — pas de session créée, on répond OK pour ne pas
            # bloquer le routeur MikroTik (il n'a rien à faire de cette erreur).
            return Response({'ok': False, 'detail': 'client inconnu'}, status=status.HTTP_200_OK)

        return Response(
            {'ok': True, 'session_id': str(session.session_key)},
            status=status.HTTP_201_CREATED,
        )


class HotspotLogoutView(APIView):
    """
    POST /api/v1/sessions/logout/

    Appelé par le script on-logout du routeur MikroTik.
    Authentification via owner_key.
    Temps de réponse non critique (client déjà parti).
    """
    authentication_classes = []  # Pas de JWT — le routeur s'authentifie via owner_key
    permission_classes = [AllowAny]
    throttle_scope = 'hotspot'

    def post(self, request):
        serializer = HotspotLogoutSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        data = serializer.validated_data
        try:
            owner = validate_owner_key(str(data['owner_key']))
        except ValueError as e:
            return Response({'detail': str(e)}, status=status.HTTP_401_UNAUTHORIZED)

        handle_logout(owner, data)
        return Response({'ok': True})


# ============================================================
# Plans tarifaires
# ============================================================

class TicketPlanViewSet(viewsets.ModelViewSet):
    """CRUD complet sur les plans tarifaires de l'owner connecté."""
    serializer_class   = TicketPlanSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return TicketPlan.objects.filter(owner=self.request.user)

    def perform_create(self, serializer):
        serializer.save(owner=self.request.user)


# ============================================================
# Analytics sessions
# ============================================================

class SessionAnalyticsViewSet(viewsets.ViewSet):
    permission_classes = [IsAuthenticated]

    def _base_qs(self):
        return ConnectionSession.objects.filter(owner=self.request.user)

    @action(detail=False, methods=['get'])
    def overview(self, request):
        date_from = request.query_params.get('date_from')
        now = timezone.now()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

        if date_from:
            try:
                from datetime import date as date_cls, datetime as datetime_cls
                from django.utils.timezone import make_aware, is_naive
                d = date_cls.fromisoformat(date_from)
                naive_cutoff = datetime_cls(d.year, d.month, d.day, 0, 0, 0)
                cutoff = make_aware(naive_cutoff) if is_naive(naive_cutoff) else naive_cutoff
            except (ValueError, TypeError):
                cutoff = today_start
        else:
            try:
                days = int(request.query_params.get('days', 30))
            except (TypeError, ValueError):
                days = 30
            cutoff = now - timedelta(days=days)

        qs = self._base_qs().filter(started_at__gte=cutoff)

        all_qs = self._base_qs()
        week_start  = today_start - timedelta(days=today_start.weekday())
        month_start = today_start.replace(day=1)

        agg = qs.aggregate(
            total_sessions=Count('id'),
            total_bytes=Sum(F('bytes_downloaded') + F('bytes_uploaded')),
            avg_uptime=Avg('uptime_seconds'),
        )
        revenue_today = all_qs.filter(
            started_at__gte=today_start, ticket_plan__isnull=False
        ).aggregate(total=Sum('ticket_plan__price_fcfa'))['total'] or 0
        revenue_week  = all_qs.filter(
            started_at__gte=week_start, ticket_plan__isnull=False
        ).aggregate(total=Sum('ticket_plan__price_fcfa'))['total'] or 0
        revenue_month = all_qs.filter(
            started_at__gte=month_start, ticket_plan__isnull=False
        ).aggregate(total=Sum('ticket_plan__price_fcfa'))['total'] or 0

        return Response({
            'total_sessions':                 agg['total_sessions'] or 0,
            'sessions_today':                 all_qs.filter(started_at__gte=today_start).count(),
            'sessions_this_week':             all_qs.filter(started_at__gte=week_start).count(),
            'sessions_this_month':            all_qs.filter(started_at__gte=month_start).count(),
            'active_sessions':                all_qs.filter(is_active=True).count(),
            'avg_session_seconds':            int(agg['avg_uptime'] or 0),
            'total_mb':                       round((agg['total_bytes'] or 0) / (1024 ** 2), 2),
            'estimated_revenue_today_fcfa':   revenue_today,
            'estimated_revenue_week_fcfa':    revenue_week,
            'estimated_revenue_month_fcfa':   revenue_month,
        })

    @action(detail=False, methods=['get'], url_path='by-day')
    def by_day(self, request):
        date_from = request.query_params.get('date_from')
        now = timezone.now()
        if date_from:
            try:
                from datetime import date as date_cls, datetime as datetime_cls
                from django.utils.timezone import make_aware, is_naive
                d = date_cls.fromisoformat(date_from)
                naive_cutoff = datetime_cls(d.year, d.month, d.day, 0, 0, 0)
                cutoff = make_aware(naive_cutoff) if is_naive(naive_cutoff) else naive_cutoff
            except (ValueError, TypeError):
                cutoff = now.replace(hour=0, minute=0, second=0, microsecond=0)
        else:
            try:
                days = max(1, min(int(request.query_params.get('days', 30)), 90))
            except (TypeError, ValueError):
                days = 30
            cutoff = now - timedelta(days=days)

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
        rows = (
            self._base_qs()
            .values(
                'client_id', 'client__email', 'client__phone', 'client__mac_address',
                'client__first_name', 'client__last_name',
            )
            .annotate(
                sessions_count=Count('id'),
                total_seconds=Sum('uptime_seconds'),
                total_bytes=Sum(F('bytes_downloaded') + F('bytes_uploaded')),
            )
            .order_by('-sessions_count')[:10]
        )
        return Response([
            {
                'client_id':      r['client_id'],
                'first_name':     r['client__first_name'] or None,
                'last_name':      r['client__last_name'] or None,
                'email':          r['client__email'],
                'phone':          r['client__phone'],
                'mac_address':    r['client__mac_address'],
                'sessions_count': r['sessions_count'],
                'total_seconds':  r['total_seconds'] or 0,
                'total_mb':       round((r['total_bytes'] or 0) / (1024 ** 2), 2),
            }
            for r in rows
        ])


# ============================================================
# Historique sessions (lecture seule)
# ============================================================

class ConnectionSessionViewSet(mixins.ListModelMixin,
                               mixins.RetrieveModelMixin,
                               viewsets.GenericViewSet):
    serializer_class   = ConnectionSessionSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = ConnectionSession.objects.filter(owner=self.request.user) \
            .select_related('client', 'ticket_plan')

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
