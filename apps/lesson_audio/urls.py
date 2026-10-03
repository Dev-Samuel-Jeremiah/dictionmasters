from django.urls import path

from . import views

app_name = "lesson_audio"

urlpatterns = [
    path("", views.hub, name="hub"),
    path("new/", views.create, name="create"),
    path("<int:pk>/", views.note_page, name="note"),
    path("<int:pk>/save/", views.save, name="save"),
    path("<int:pk>/audio/", views.make_audio, name="audio"),
    path("<int:pk>/status/", views.status, name="status"),
    path("<int:pk>/keywords/", views.refresh_keywords, name="keywords"),
    path("<int:pk>/words/add/", views.add_word, name="add_word"),
    path("<int:pk>/words/<int:word_id>/remove/", views.remove_word, name="remove_word"),
    path("<int:pk>/words/<int:word_id>/practise/", views.practise, name="practise"),
    path("<int:pk>/download/", views.download, name="download"),
    path("<int:pk>/copy/", views.copy, name="copy"),
    path("<int:pk>/delete/", views.delete, name="delete"),
]
