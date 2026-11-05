from django.urls import path

from . import views

app_name = "offline"

urlpatterns = [
    path("manifest/", views.offline_manifest, name="manifest"),
    path("video/<str:ref>/", views.video_ticket, name="video_ticket"),
    path("pack/<int:pk>/", views.pack_key, name="pack_key"),
]
