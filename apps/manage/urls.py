from django.urls import path

from . import scheme_editor, views

app_name = "manage"

urlpatterns = [
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("", views.home, name="home"),
    path("search/", views.search, name="search"),
    path("jobs/<str:job>/", views.run_job, name="job"),
    path("branding/", views.branding, name="branding"),
    path("billing-settings/", views.billing_settings, name="billing_settings"),
    path("analytics/", views.analytics_view, name="analytics"),
    path("schools-directory/", views.schools_directory, name="schools_directory"),
    path("schools-directory/bulk-register/", views.bulk_schools, name="bulk_schools"),
    path("schools-directory/<int:pk>/", views.school_people, name="school_people"),
    path("schools-directory/<int:pk>/logins/", views.school_login_sheet, name="school_login_sheet"),
    path("bulk-students/", views.bulk_students, name="bulk_students"),
    path("bulk-teachers/", views.bulk_teachers, name="bulk_teachers"),
    path("read-along/", views.read_along, name="read_along"),
    path("read-along/<int:pk>/", views.read_along_detail, name="read_along_detail"),
    path("echospell-import/", views.echospell_import, name="echospell_import"),
    path("recitals/upload-audio-zip/", views.assembly_recital_audio_upload, name="assembly_recital_audio_upload"),
    path("groups/", views.groups_overview, name="groups_overview"),
    path("results/", views.results_list, name="results"),
    path("results/<str:source>/<int:pk>/", views.result_detail, name="result"),
    path("words/upload-zip/", views.quick_words_audio_upload, name="quick_words_audio_upload"),
    path("words/upload-zip/<uuid:job_id>/", views.quick_words_audio_import, name="quick_words_audio_import"),
    path("lesson-items/<int:pk>/slides/", views.lesson_slides, name="lesson_slides"),
    path("scheme-of-work/", scheme_editor.scheme_editor, name="scheme_editor"),
    path("<slug:key>/", views.record_list, name="list"),
    path("<slug:key>/new/", views.record_form, name="add"),
    path("<slug:key>/bulk/", views.bulk_questions, name="bulk_questions"),
    path("<slug:key>/delete-selected/", views.record_delete_many, name="delete_many"),
    path("<slug:key>/<str:pk>/", views.record_form, name="edit"),
    path("<slug:key>/<str:pk>/delete/", views.record_delete, name="delete"),
]
