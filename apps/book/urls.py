from django.urls import path

from . import views

app_name = "book"

urlpatterns = [
    path("", views.home, name="home"),
    path("phonemic-chart/", views.phonemic_chart, name="phonemic_chart"),
    path("44-academy/", views.academy, name="academy"),
    path("read-along/<str:token>/", views.read_along_timing, name="read_along"),
    path("44-academy/<slug:slug>/", views.sound_detail, name="sound_detail"),
    path("44-academy/<slug:slug>/<str:tab>/", views.sound_detail, name="sound_detail_tab"),
]
