from django.urls import path

from . import views

app_name = "reading_club"

urlpatterns = [
    path("", views.hub, name="hub"),
    path("<slug:book_slug>/", views.book_detail, name="book_detail"),
    path("<slug:book_slug>/<slug:term_slug>/", views.term_detail, name="term_detail"),
    path("<slug:book_slug>/<slug:term_slug>/<slug:chapter_slug>/", views.chapter_detail, name="chapter_detail"),
    path(
        "<slug:book_slug>/<slug:term_slug>/<slug:chapter_slug>/complete/",
        views.toggle_complete,
        name="toggle_complete",
    ),
]
