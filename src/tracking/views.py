# tracking/views.py
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from django.utils.decorators import method_decorator

from .serializers import HeartbeatSerializer, EndSessionSerializer
from .services import handle_heartbeat, close_session
from core_data.decorators import ratelimit_public_api   # réutilise le décorateur existant


class TrackingViewSet(viewsets.ViewSet):
    permission_classes = [AllowAny]

    @method_decorator(ratelimit_public_api(requests=30, duration=60))
    @action(detail=False, methods=['post'])
    def heartbeat(self, request):
        """
        Reçoit les données de session de tracker.js.
        Appelé à chaque refresh de la page status.html par MikroTik.
        """
        serializer = HeartbeatSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        try:
            session, created = handle_heartbeat(serializer.validated_data)
            return Response({
                'ok': True,
                'session_key': str(session.session_key),
                'created': created,
            }, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)

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
