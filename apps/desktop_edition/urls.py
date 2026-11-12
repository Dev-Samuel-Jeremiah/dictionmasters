from django.urls import path

from . import views

app_name = "desktop_edition"

urlpatterns = [
    path("activate/", views.activate, name="activate"),
    path("check/", views.check, name="check"),
    path("content/latest/", views.latest, name="latest"),
    path("content/blob/<str:blob_id>/", views.blob, name="blob"),
    path("public-key/", views.public_key, name="public_key"),
    path("downloads/<int:pk>/", views.bundle_download, name="bundle_download"),
]
