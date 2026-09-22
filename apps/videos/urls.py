from django.urls import path

from . import views

app_name = "videos"

urlpatterns = [
    path("play/<str:ticket>/", views.play, name="play"),
    path("keep/<str:ticket>/", views.keep, name="keep"),
    path("prepare/", views.prepare, name="prepare"),
    path("licenses/", views.licenses, name="licenses"),
    path("release/", views.release, name="release"),
    path("devices/", views.devices, name="devices"),
    path("devices/<int:pk>/deactivate/", views.deactivate_device, name="deactivate_device"),
    path("offline/", views.offline_page, name="offline"),
]
