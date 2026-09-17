from django.urls import path

from . import views

app_name = "assessments"

# Every fixed word ("type", "attempt", "results", "marking") is matched
# before the assessment slug at the bottom, so no slug can shadow them.
urlpatterns = [
    path("", views.hub, name="hub"),
    path("type/<slug:kind>/", views.kind_list, name="kind_list"),
    path("results/", views.my_results, name="my_results"),
    path("marking/", views.marking_queue, name="marking_queue"),
    path("marking/<int:attempt_id>/", views.mark, name="mark"),
    path("attempt/<int:attempt_id>/", views.take, name="take"),
    path("attempt/<int:attempt_id>/save/", views.save_answer, name="save_answer"),
    path("attempt/<int:attempt_id>/check/", views.check_answer, name="check_answer"),
    path("attempt/<int:attempt_id>/result/", views.result, name="result"),
    path("<slug:slug>/", views.detail, name="detail"),
    path("<slug:slug>/start/", views.start, name="start"),
]
