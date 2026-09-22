from django.urls import path

from . import views

app_name = "tutor"

urlpatterns = [
    path("", views.hub, name="hub"),
    path("voice/", views.choose_voice, name="choose_voice"),
    path("voice/<int:pk>/sample/", views.voice_sample, name="voice_sample"),
    path("read/<int:pk>/", views.read, name="read"),
    path("read/<int:pk>/start/", views.start, name="start"),
    path("read/<int:pk>/hear/", views.hear_passage, name="hear_passage"),
    path("session/<int:session_id>/piece/", views.piece, name="piece"),
    path("session/<int:session_id>/check/", views.check, name="check"),
    path("session/<int:session_id>/say/", views.say, name="say"),
    path("session/<int:session_id>/finish/", views.finish, name="finish"),
    path("session/<int:session_id>/", views.report_page, name="report"),
]
