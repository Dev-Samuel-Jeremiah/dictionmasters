from django.urls import path

from . import views

app_name = "echospell"

urlpatterns = [
    path("", views.hub, name="hub"),
    path("vocabulary/check-sentences/", views.check_vocabulary_sentences, name="check_vocabulary_sentences"),
    path("<slug:level_slug>/", views.level_detail, name="level_detail"),
    path("<slug:level_slug>/<slug:group_slug>/", views.group_detail, name="group_detail"),
    path(
        "<slug:level_slug>/<slug:group_slug>/activities/<slug:activity_slug>/",
        views.activity_detail, name="activity_detail",
    ),
    path(
        "<slug:level_slug>/<slug:group_slug>/activities/<slug:activity_slug>/result/<int:attempt_id>/",
        views.activity_result, name="activity_result",
    ),
    path("<slug:level_slug>/<slug:group_slug>/complete/", views.toggle_complete, name="toggle_complete"),
    path("<slug:level_slug>/<slug:group_slug>/<slug:category_slug>/", views.card_detail, name="card_detail"),
]
