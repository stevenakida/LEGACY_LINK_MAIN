from django.urls import path
from .views import SchoolSearchView, CompleteOnboardingView, CohortMatchView

urlpatterns = [
    path('schools/', SchoolSearchView.as_view(), name='schools'),
    path('onboarding/', CompleteOnboardingView.as_view(), name='onboarding'),
    path('cohort/', CohortMatchView.as_view(), name='cohort'),
]