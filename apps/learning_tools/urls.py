from django.urls import path

from . import views

app_name = "learning_tools"

urlpatterns = [
    path("", views.hub, name="hub"),
    path("book-scanner/", views.book_scanner, name="book_scanner"),
    path("book-scanner/recognize/", views.book_scanner_recognize, name="book_scanner_recognize"),
    path("book-scanner/narrate/", views.book_scanner_narrate, name="book_scanner_narrate"),
]
