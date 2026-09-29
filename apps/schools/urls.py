from django.urls import path

from . import views

app_name = "schools"

urlpatterns = [
    path("dashboard/", views.dashboard, name="dashboard"),
    path("members/<int:pk>/remove/", views.remove_member, name="remove_member"),
    path("members/<int:pk>/restore/", views.restore_member, name="restore_member"),
]
