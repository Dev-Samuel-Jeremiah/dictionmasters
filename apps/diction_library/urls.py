from django.urls import path

from . import views

app_name = "diction_library"

urlpatterns = [
    path("", views.hub, name="hub"),
    path("manage/", views.manage, name="manage"),
    path("manage/new/", views.edit_item, name="add"),
    path("manage/<int:pk>/edit/", views.edit_item, name="edit"),
    path("manage/<int:pk>/delete/", views.delete_item, name="delete"),
    path("<slug:slug>/", views.item_detail, name="detail"),
]
