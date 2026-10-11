from django.urls import path

from . import views

app_name = "notifications"

urlpatterns = [
    path("", views.page, name="page"),
    path("panel/", views.panel, name="panel"),
    path("count/", views.count, name="count"),
    path("<int:pk>/", views.open_one, name="open"),
    path("read-all/", views.read_all, name="read_all"),
]
