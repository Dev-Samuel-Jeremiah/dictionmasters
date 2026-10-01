from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("register/", views.register_choice, name="register_choice"),
    path("register/school/", views.register_school, name="register_school"),
    path("register/school-team/", views.register_school_team, name="register_school_team"),
    path("register/individual/", views.register_individual, name="register_individual"),
    path("register/student/", views.register_student, name="register_student"),
    path("join/", views.join_with_code, name="join_with_code"),
    path("login/", views.EmailLoginView.as_view(), name="login"),
    path("logout/", views.EmailLogoutView.as_view(), name="logout"),
    path("dashboard/", views.dashboard, name="dashboard"),
    path("switch/", views.switch_account, name="switch_account"),
    path("switch/add/", views.add_account, name="add_account"),
    path("switch/remove/", views.remove_account, name="remove_account"),
    path("switch/forget/", views.forget_accounts, name="forget_accounts"),
    path("delete/", views.delete_account, name="delete_account"),
]
