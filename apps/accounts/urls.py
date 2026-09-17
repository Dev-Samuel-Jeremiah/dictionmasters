from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("register/", views.register_choice, name="register_choice"),
    path("register/school/", views.register_school, name="register_school"),
    path("register/individual/", views.register_individual, name="register_individual"),
    path("join/", views.join_with_code, name="join_with_code"),
    path("login/", views.EmailLoginView.as_view(), name="login"),
    path("logout/", views.EmailLogoutView.as_view(), name="logout"),
    path("dashboard/", views.dashboard, name="dashboard"),
]
