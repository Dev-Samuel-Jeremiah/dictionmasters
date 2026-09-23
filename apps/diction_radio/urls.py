from django.urls import path

from . import views

app_name = "diction_radio"

urlpatterns = [
    path("", views.home, name="home"),
]
