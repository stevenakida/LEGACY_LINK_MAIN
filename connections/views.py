from rest_framework import permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from . import services


class SendConnectionView(APIView):
    """POST /api/connections/send/{user_id}/  (optional body: {"message": "..."})

    Thin wrapper over connections.services.send_request, so the API enforces
    exactly the same integrity rules as the web UI."""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, user_id):
        result = services.send_request(request.user, user_id, request.data.get('message', ''))
        if result.ok:
            return Response({'message': 'Connection request sent', 'status': 'pending'}, status=201)
        if result.code == 'not_found':
            return Response({'error': 'User not found'}, status=404)
        if result.code == 'self':
            return Response({'error': 'Cannot connect with yourself'}, status=400)
        if result.code == 'blocked':
            return Response({'error': 'Cannot connect with this user'}, status=403)
        if result.code == 'rate_limited':
            return Response({'error': 'Too many connection requests, try again later'}, status=429)
        return Response({'error': 'Connection already exists'}, status=400)


class RespondConnectionView(APIView):
    """PATCH /api/connections/{id}/respond/ — Accept or Decline. Only a
    still-pending request addressed to the caller can be answered."""
    permission_classes = [permissions.IsAuthenticated]

    def patch(self, request, connection_id):
        result = services.respond_to_request(request.user, connection_id, request.data.get('action'))
        if result.ok:
            new_status = result.connection.status
            return Response({'status': new_status, 'message': f'Connection {new_status}'})
        if result.code == 'invalid_action':
            return Response({'error': 'action must be accept or decline'}, status=400)
        if result.code == 'already_resolved':
            return Response({'error': 'Connection request already answered'}, status=409)
        if result.code == 'blocked':
            return Response({'error': 'Cannot respond to this user'}, status=403)
        return Response({'error': 'Connection not found'}, status=404)


class MyConnectionsView(APIView):
    """GET /api/connections/ — List pending and accepted connections"""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        user = request.user
        tab = request.query_params.get('tab', 'pending')

        if tab == 'pending':
            # Incoming requests I haven't responded to
            conns = services.incoming_pending_qs(user)
        else:
            # All accepted connections (both sides)
            conns = services.accepted_connections_qs(user)

        from .serializers import ConnectionSerializer
        return Response(ConnectionSerializer(conns, many=True,
                         context={'request': request}).data)
