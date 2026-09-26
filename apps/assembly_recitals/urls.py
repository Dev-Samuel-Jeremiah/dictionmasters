from django.urls import path

from . import views

app_name = "assembly_recitals"

urlpatterns = [
    path("", views.hub, name="hub"),
    path("<slug:section_slug>/", views.section_detail, name="section"),
    path("<slug:section_slug>/<slug:recital_slug>/", views.recital_detail, name="recital"),
]
