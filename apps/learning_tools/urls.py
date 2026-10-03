from django.urls import path

from . import views

app_name = "learning_tools"

urlpatterns = [
    path("", views.hub, name="hub"),
    path("book-scanner/", views.book_scanner, name="book_scanner"),
    path("book-scanner/recognize/", views.book_scanner_recognize, name="book_scanner_recognize"),
    path("book-scanner/readings/save/", views.reading_save, name="reading_save"),
    path("book-scanner/readings/search/", views.reading_search, name="reading_search"),
    path("book-scanner/readings/<int:pk>/audio/", views.reading_audio, name="reading_audio"),
    path("book-scanner/readings/<int:pk>/status/", views.reading_status, name="reading_status"),
    path("book-scanner/readings/<int:pk>/delete/", views.reading_delete, name="reading_delete"),
]
