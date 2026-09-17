from django.urls import path

from . import views

app_name = "quick_words"

urlpatterns = [
    path("", views.hub, name="hub"),
    path("suggest/", views.suggest, name="suggest"),
    path("lookup/", views.lookup_word, name="lookup"),
    # Literal "lists" paths sit above the word slug so a list URL is
    # never mistaken for a word.
    path("lists/", views.my_lists, name="my_lists"),
    path("lists/new/", views.create_list, name="create_list"),
    path("lists/<int:list_id>/delete/", views.delete_list, name="delete_list"),
    path("lists/<int:list_id>/toggle/<slug:slug>/", views.toggle_word, name="toggle_word"),
    path("<slug:slug>/", views.word_detail, name="word_detail"),
]
