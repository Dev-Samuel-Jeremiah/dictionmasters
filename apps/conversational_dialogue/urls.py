from django.urls import path

from . import views

app_name = "conversational_dialogue"

urlpatterns = [
    path("", views.hub, name="hub"),
    path("<slug:level_slug>/", views.level_detail, name="level"),
    path("<slug:level_slug>/<slug:slug>/", views.dialogue_detail, name="dialogue"),
    path("<slug:level_slug>/<slug:slug>/practised/", views.toggle_done, name="toggle_done"),
]
