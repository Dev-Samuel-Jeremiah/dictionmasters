from django.urls import path

from . import views

app_name = "platform_search"
urlpatterns = [
    path("", views.results, name="results"),
    path("suggest/", views.suggest, name="suggest"),
]
