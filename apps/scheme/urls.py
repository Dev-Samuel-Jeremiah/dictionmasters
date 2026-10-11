from django.urls import path

from . import views

app_name = "scheme"

urlpatterns = [
    path("reports/", views.reports, name="reports"),
    path("reports/<int:term_pk>/<int:student_pk>/", views.card, name="card"),
    path("promote/", views.promote, name="promote"),
    path("term-dates/", views.term_dates, name="term_dates"),
]
