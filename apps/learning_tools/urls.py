from django.urls import path

from . import views

app_name = "learning_tools"

urlpatterns = [
    path("", views.hub, name="hub"),
]
