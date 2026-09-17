from django.urls import path

from . import views

app_name = "learning_modules"

urlpatterns = [
    path("", views.hub, name="hub"),
    path("<slug:module_slug>/", views.module_detail, name="module_detail"),
    path("<slug:module_slug>/<slug:term_slug>/", views.term_detail, name="term_detail"),
    path("<slug:module_slug>/<slug:term_slug>/<slug:week_slug>/", views.week_detail, name="week_detail"),
    path(
        "<slug:module_slug>/<slug:term_slug>/<slug:week_slug>/<str:day_name>/",
        views.day_detail,
        name="day_detail",
    ),
    path(
        "<slug:module_slug>/<slug:term_slug>/<slug:week_slug>/<str:day_name>/complete/",
        views.toggle_complete,
        name="toggle_complete",
    ),
]
