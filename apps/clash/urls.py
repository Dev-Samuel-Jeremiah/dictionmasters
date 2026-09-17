from django.urls import path

from . import views

app_name = "clash"

urlpatterns = [
    path("", views.hub, name="hub"),
    path("start/", views.start, name="start"),
    path("sound/", views.toggle_sound, name="toggle_sound"),
    path("<int:match_id>/", views.play, name="play"),
    path("<int:match_id>/result/", views.result, name="result"),
]
