from django.urls import path

from . import views

app_name = "tricks"

urlpatterns = [
    path("", views.home, name="home"),
    path("lessons/", views.lessons, name="lessons"),
    path("sections/", views.sections, name="sections"),
    path("sections/<slug:section>/", views.sections, name="section"),
    path("lessons/<slug:slug>/", views.lesson, name="lesson"),
    path("lessons/<slug:slug>/<str:tab>/", views.lesson, name="lesson_tab"),
]
