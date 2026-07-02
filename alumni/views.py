from rest_framework import generics, permissions
from rest_framework.response import Response
from rest_framework.views import APIView
from django.db import models
from .models import School
from .serializers import SchoolSerializer


class SchoolSearchView(generics.ListAPIView):
    """GET /api/alumni/schools/?q=Jangwani — Searchable school list"""
    serializer_class = SchoolSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        query = self.request.query_params.get('q', '')
        qs = School.objects.filter(is_active=True)
        if query:
            qs = qs.filter(name__icontains=query)
        return qs[:20]  # Limit to 20 suggestions


class CompleteOnboardingView(APIView):
    """PATCH /api/alumni/onboarding/ — Set school + graduation year"""
    permission_classes = [permissions.IsAuthenticated]

    def patch(self, request):
        user = request.user
        school_id = request.data.get('school_id')
        graduation_year = request.data.get('graduation_year')

        if not school_id or not graduation_year:
            return Response(
                {'error': 'school_id and graduation_year are required'},
                status=400
            )

        try:
            school = School.objects.get(id=school_id)
        except School.DoesNotExist:
            return Response({'error': 'School not found'}, status=404)

        user.school = school
        user.graduation_year = int(graduation_year)
        user.onboarding_complete = True
        user.save()

        from accounts.serializers import UserProfileSerializer
        return Response(UserProfileSerializer(user).data)


from accounts.models import User
from accounts.serializers import UserProfileSerializer
from connections.models import Connection


class CohortMatchView(APIView):
    """GET /api/alumni/cohort/ — Returns classmates for the logged-in user"""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        user = request.user

        if not user.onboarding_complete:
            return Response(
                {'error': 'Complete onboarding first'},
                status=400
            )

        # PRIMARY MATCH RULE: same school + same graduation year
        cohort = User.objects.filter(
            school=user.school,
            graduation_year=user.graduation_year,
            onboarding_complete=True
        ).exclude(id=user.id)  # Exclude self

        # Get IDs of users this person already connected with
        existing = Connection.objects.filter(
            models.Q(requester=user) | models.Q(receiver=user)
        ).values_list('requester_id', 'receiver_id')

        connected_ids = set()
        for r, rv in existing:
            connected_ids.add(str(r))
            connected_ids.add(str(rv))
        connected_ids.discard(str(user.id))

        # Annotate connection status for each cohort member
        results = []
        for member in cohort:
            data = UserProfileSerializer(member).data
            data['connection_status'] = 'none'
            if str(member.id) in connected_ids:
                conn = Connection.objects.filter(
                    models.Q(requester=user, receiver=member) |
                    models.Q(requester=member, receiver=user)
                ).first()
                if conn:
                    data['connection_status'] = conn.status
            results.append(data)

        return Response({
            'school': user.school.name,
            'graduation_year': user.graduation_year,
            'cohort_count': len(results),
            'members': results
        })
