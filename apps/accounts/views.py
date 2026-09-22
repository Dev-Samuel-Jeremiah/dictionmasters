from django.contrib import messages
from django.contrib.auth import login as auth_login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView, LogoutView
from django.shortcuts import redirect, render
from django.urls import reverse_lazy

from apps.billing.models import Plan
from apps.billing.services import begin_access

from .dashboard_data import learner_dashboard
from .forms import (
    EmailAuthenticationForm,
    IndividualRegistrationForm,
    JoinWithCodeForm,
    SchoolRegistrationForm,
    StudentRegistrationForm,
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


def _chosen_plan(form, audience):
    slug = form.cleaned_data.get("plan")
    return Plan.objects.filter(slug=slug, audience=audience, is_active=True).first() if slug else None


def register_school(request):
    if request.method == "POST":
        form = SchoolRegistrationForm(request.POST)
        if form.is_valid():
            user = form.save()
            auth_login(request, user)
            messages.success(
                request,
                f"{user.school.name} is set up. Your school code is {user.school.code} — "
                "teachers join with codes you make, and students sign up with this school code.",
            )
            return redirect(begin_access(request, user, form.cleaned_data.get("start"), _chosen_plan(form, Plan.AUDIENCE_SCHOOL),
                                          form.cleaned_data.get("promo_code", "")))
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
            return redirect(begin_access(request, user, form.cleaned_data.get("start"), _chosen_plan(form, Plan.AUDIENCE_INDIVIDUAL),
                                          form.cleaned_data.get("promo_code", "")))
    else:
        form = IndividualRegistrationForm()
    return render(request, "accounts/register_individual.html", {"form": form})


def register_student(request):
    if request.method == "POST":
        form = StudentRegistrationForm(request.POST)
        if form.is_valid():
            user = form.save()
            auth_login(request, user)
            messages.success(request, f"Welcome, {user.first_name}! You're now part of {user.school.name}.")
            return redirect(begin_access(request, user, form.cleaned_data.get("start"), form.chosen_plan(user),
                                          form.cleaned_data.get("promo_code", "")))
    else:
        form = StudentRegistrationForm(initial={"school_code": request.GET.get("school", "")})
    return render(request, "accounts/register_student.html", {"form": form})


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
        # Where they were heading before signing in — scanning a QR code on
        # a card, following a link — wins over the usual home page.
        wanted = self.get_redirect_url()
        return wanted or reverse_lazy(_post_login_redirect(self.request.user))


class EmailLogoutView(LogoutView):
    next_page = reverse_lazy("landing:home")


@login_required(login_url="accounts:login")
def dashboard(request):
    """The learner's home: streak, progress across every tool, where to
    carry on, and the tools themselves."""
    if request.user.role == User.Role.SCHOOL_ADMIN:
        return redirect("schools:dashboard")
    return render(request, "accounts/dashboard.html", learner_dashboard(request.user))
