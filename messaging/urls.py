from django.urls import path
from .views import ConversationListView, ConversationMessagesView

# Named distinctly from config/urls.py's web-page messaging views — see the
# comment in alumni/urls.py for why colliding names are a problem.
urlpatterns = [
    path('conversations/', ConversationListView.as_view(), name='api_conversations'),
    path('conversations/<uuid:conversation_id>/messages/', ConversationMessagesView.as_view(), name='api_conversation_messages'),
]
