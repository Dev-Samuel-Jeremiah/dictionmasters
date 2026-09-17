from django.urls import path

from . import views

app_name = "daily_practice"

urlpatterns = [
    path("", views.home, name="home"),
]
