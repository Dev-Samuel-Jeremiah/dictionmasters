from django.urls import path

from . import views

app_name = "tutor"

urlpatterns = [
    path("", views.hub, name="hub"),
    path("read/<int:pk>/", views.read, name="read"),
    path("read/<int:pk>/start/", views.start, name="start"),
    path("session/<int:session_id>/check/", views.check, name="check"),
    path("session/<int:session_id>/say/", views.say, name="say"),
    path("session/<int:session_id>/finish/", views.finish, name="finish"),
    path("session/<int:session_id>/", views.report_page, name="report"),
]
