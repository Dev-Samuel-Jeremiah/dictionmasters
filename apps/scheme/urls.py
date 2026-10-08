from django.urls import path

from . import views

app_name = "scheme"

urlpatterns = [
    path("reports/", views.reports, name="reports"),
    path("reports/<int:term_pk>/<int:student_pk>/", views.card, name="card"),
    path("promote/", views.promote, name="promote"),
    path("term-dates/", views.term_dates, name="term_dates"),
    path("school/", views.school_scheme, name="school_scheme"),
    path("teach/", views.teaching_plan, name="teaching_plan"),
    path("weeks/", views.weeks, name="weeks"),
    path("lessons/", views.lessons, name="lessons"),
    path("practise/", views.practise, name="practise"),
    path("weeks/<int:term>/<int:number>/", views.week, name="week"),
    path("go/<int:pk>/", views.go, name="go"),
    path("choose/", views.choose, name="choose"),
]
