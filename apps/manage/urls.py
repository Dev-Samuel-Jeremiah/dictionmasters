from django.urls import path

from . import views

app_name = "manage"

urlpatterns = [
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("", views.home, name="home"),
    path("search/", views.search, name="search"),
    path("jobs/<str:job>/", views.run_job, name="job"),
    path("branding/", views.branding, name="branding"),
    path("billing-settings/", views.billing_settings, name="billing_settings"),
    path("read-along/", views.read_along, name="read_along"),
    path("read-along/<int:pk>/", views.read_along_detail, name="read_along_detail"),
    path("echospell-import/", views.echospell_import, name="echospell_import"),
    path("results/", views.results_list, name="results"),
    path("results/<str:source>/<int:pk>/", views.result_detail, name="result"),
    path("<slug:key>/", views.record_list, name="list"),
    path("<slug:key>/new/", views.record_form, name="add"),
    path("<slug:key>/bulk/", views.bulk_questions, name="bulk_questions"),
    path("<slug:key>/<str:pk>/", views.record_form, name="edit"),
    path("<slug:key>/<str:pk>/delete/", views.record_delete, name="delete"),
]
