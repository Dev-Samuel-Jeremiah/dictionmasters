from django.contrib import messages
from django.contrib.auth import login as auth_login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView, LogoutView
from django.shortcuts import redirect, render
from django.urls import reverse_lazy

from .dashboard_data import learner_dashboard
from .forms import (
    EmailAuthenticationForm,
    IndividualRegistrationForm,
    JoinWithCodeForm,
    SchoolRegistrationForm,
)
from .models import User


def _post_login_redirect(user):
    """Where someone lands right after signing in, based on role.

    Only the school app exists so far, so every non-admin role goes
    to the same holding dashboard for now — swapping it for the real
    teacher/student home later is a one-line change here.
    """
    if user.role == User.Role.SCHOOL_ADMIN:
        return "schools:dashboard"
    return "accounts:dashboard"


def register_choice(request):
    """The hub: school, individual, or "I have a code from my school"."""
    return render(request, "accounts/register_choice.html")


def register_school(request):
    if request.method == "POST":
        form = SchoolRegistrationForm(request.POST)
        if form.is_valid():
            user = form.save()
            auth_login(request, user)
            messages.success(
                request,
                f"{user.school.name} is set up. Your school code is "
                f"{user.school.code} — you can now add teachers and students.",
            )
            return redirect(_post_login_redirect(user))
    else:
        form = SchoolRegistrationForm()
    return render(request, "accounts/register_school.html", {"form": form})


def register_individual(request):
    if request.method == "POST":
        form = IndividualRegistrationForm(request.POST)
        if form.is_valid():
            user = form.save()
            auth_login(request, user)
            messages.success(request, "Welcome to Diction Masters!")
            return redirect(_post_login_redirect(user))
    else:
        form = IndividualRegistrationForm()
    return render(request, "accounts/register_individual.html", {"form": form})


def join_with_code(request):
    if request.method == "POST":
        form = JoinWithCodeForm(request.POST)
        if form.is_valid():
            user = form.save()
            auth_login(request, user)
            messages.success(request, f"You're in, {user.first_name}. Welcome to {user.school.name}.")
            return redirect(_post_login_redirect(user))
    else:
        form = JoinWithCodeForm()
    return render(request, "accounts/join_with_code.html", {"form": form})


class EmailLoginView(LoginView):
    template_name = "accounts/login.html"
    authentication_form = EmailAuthenticationForm
    redirect_authenticated_user = True

    def get_success_url(self):
        return reverse_lazy(_post_login_redirect(self.request.user))


class EmailLogoutView(LogoutView):
    next_page = reverse_lazy("landing:home")


@login_required(login_url="accounts:login")
def dashboard(request):
    """The learner's home: streak, progress across every tool, where to
    carry on, and the tools themselves."""
    if request.user.role == User.Role.SCHOOL_ADMIN:
        return redirect("schools:dashboard")
    return render(request, "accounts/dashboard.html", learner_dashboard(request.user))
