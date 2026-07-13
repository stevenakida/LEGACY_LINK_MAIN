from rest_framework import generics, permissions
from .models import Opportunity
from .serializers import OpportunitySerializer


class OpportunityListView(generics.ListAPIView):
    """GET /api/opportunities/?type=job|mentorship|event — for the Android
    app. Web-facing filtering/listing lives in config/views.py instead, same
    dual-stack split used by every other app in this project."""
    serializer_class = OpportunitySerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        qs = Opportunity.objects.filter(is_active=True).select_related('school_scope')
        opp_type = self.request.query_params.get('type')
        if opp_type in dict(Opportunity.TYPE_CHOICES):
            qs = qs.filter(type=opp_type)
        return qs

    def get_serializer_context(self):
        return {'request': self.request}
