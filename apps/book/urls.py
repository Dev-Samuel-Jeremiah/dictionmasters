from django.urls import path

from . import views

app_name = "book"

urlpatterns = [
    path("", views.home, name="home"),
    path("phonemic-chart/", views.phonemic_chart, name="phonemic_chart"),
    path("44-academy/", views.academy, name="academy"),
    # Tricks to Sound Fluent now has a home of its own at /tricks/.
    path("tricks/", views.moved_to_tricks),
    path("tricks/<slug:section>/", views.moved_to_tricks),
    path("read-along/<str:token>/", views.read_along_timing, name="read_along"),
    path("44-academy/<slug:slug>/", views.sound_detail, name="sound_detail"),
    # A sound's assessment activities (apps/tricks/views.py, shared with Tricks).
    path("44-academy/<slug:slug>/assessment/<slug:activity_slug>/", views.sound_activity, name="sound_activity"),
    path("44-academy/<slug:slug>/assessment/<slug:activity_slug>/result/<int:attempt_id>/",
         views.sound_activity_result, name="sound_activity_result"),
    path("44-academy/<slug:slug>/<str:tab>/", views.sound_detail, name="sound_detail_tab"),
]
