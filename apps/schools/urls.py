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
    path("logins/unlock/", views.logins_unlock, name="logins_unlock"),
    path("logins/help/<int:pk>/dismiss/", views.dismiss_help, name="dismiss_help"),
    path("logins/download/", views.logins_download, name="logins_download"),
    path("logins/reset/", views.bulk_reset, name="bulk_reset"),
    path("members/<int:pk>/login/", views.member_login, name="member_login"),
    path("members/<int:pk>/reset-password/", views.member_reset, name="member_reset"),
]
