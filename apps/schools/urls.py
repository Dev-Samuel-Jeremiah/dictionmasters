from django.urls import path

from . import views

app_name = "schools"

urlpatterns = [
    path("dashboard/", views.dashboard, name="dashboard"),
    path("members/<int:pk>/remove/", views.remove_member, name="remove_member"),
    path("members/<int:pk>/restore/", views.restore_member, name="restore_member"),
    path("members/<int:pk>/level/", views.member_level, name="member_level"),
    path("members/levels/", views.bulk_levels, name="bulk_levels"),
    path("levels/undo/<str:batch>/", views.undo_levels, name="undo_levels"),
]
