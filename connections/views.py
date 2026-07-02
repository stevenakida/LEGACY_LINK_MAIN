from rest_framework import status, permissions
from rest_framework.response import Response
from rest_framework.views import APIView
from django.db import models
from .models import Connection
from accounts.models import User


class SendConnectionView(APIView):
    """POST /api/connections/send/{user_id}/"""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, user_id):
        try:
            receiver = User.objects.get(id=user_id)
        except User.DoesNotExist:
            return Response({'error': 'User not found'}, status=404)

        if receiver == request.user:
            return Response({'error': 'Cannot connect with yourself'}, status=400)

        conn, created = Connection.objects.get_or_create(
            requester=request.user, receiver=receiver
        )
        if not created:
            return Response({'error': 'Connection already exists'}, status=400)

        return Response({'message': 'Connection request sent', 'status': 'pending'}, status=201)


class RespondConnectionView(APIView):
    """PATCH /api/connections/{id}/respond/ — Accept or Decline"""
    permission_classes = [permissions.IsAuthenticated]

    def patch(self, request, connection_id):
        try:
            conn = Connection.objects.get(id=connection_id, receiver=request.user)
        except Connection.DoesNotExist:
            return Response({'error': 'Connection not found'}, status=404)

        action = request.data.get('action')  # 'accept' or 'decline'
        if action == 'accept':
            conn.status = 'accepted'
        elif action == 'decline':
            conn.status = 'declined'
        else:
            return Response({'error': 'action must be accept or decline'}, status=400)

        conn.save()
        return Response({'status': conn.status, 'message': f'Connection {conn.status}'})


class MyConnectionsView(APIView):
    """GET /api/connections/ — List pending and accepted connections"""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        user = request.user
        tab = request.query_params.get('tab', 'pending')

        if tab == 'pending':
            # Incoming requests I haven't responded to
            conns = Connection.objects.filter(receiver=user, status='pending')
        else:
            # All accepted connections (both sides)
            conns = Connection.objects.filter(
                models.Q(requester=user) | models.Q(receiver=user),
                status='accepted'
            )

        from .serializers import ConnectionSerializer
        return Response(ConnectionSerializer(conns, many=True,
                         context={'request': request}).data)
