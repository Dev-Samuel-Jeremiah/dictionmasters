from django.urls import path

from . import views

app_name = "offline"

urlpatterns = [
    path("manifest/", views.offline_manifest, name="manifest"),
]
