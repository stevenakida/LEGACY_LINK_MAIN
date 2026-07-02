from django.urls import path
from .views import SendConnectionView, RespondConnectionView, MyConnectionsView

urlpatterns = [
    path('', MyConnectionsView.as_view(), name='connections'),
    path('send/<uuid:user_id>/', SendConnectionView.as_view(), name='send'),
    path('<uuid:connection_id>/respond/', RespondConnectionView.as_view(), name='respond'),
]