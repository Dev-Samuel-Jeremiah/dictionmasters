from django.urls import path

from . import views

app_name = "schools"

urlpatterns = [
    path("dashboard/", views.dashboard, name="dashboard"),
]
