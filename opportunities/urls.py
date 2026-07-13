from django.urls import path
from .views import OpportunityListView

# Named distinctly from config/urls.py's web-page 'opportunities' view — see
# the comment in alumni/urls.py for why colliding names are a problem.
urlpatterns = [
    path('', OpportunityListView.as_view(), name='api_opportunities'),
]
