import logging
from urllib.parse import quote

from django.contrib import messages
from django.contrib.auth import login as auth_login
from django.contrib.auth import logout as auth_logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView, LogoutView
from django.shortcuts import redirect, render
from django.urls import reverse_lazy
from django.views.decorators.http import require_POST

from apps.billing.access import subscription_for
from apps.billing.models import Plan
from apps.billing.services import begin_access

from .dashboard_data import learner_dashboard
from .forms import (
    EmailAuthenticationForm,
    IndividualRegistrationForm,
    SchoolTeamMemberForm,
    SchoolTeamRegistrationForm,
    TeacherRegistrationForm,
    SchoolRegistrationForm,
    StudentRegistrationForm,
)
from . import switcher
from .welcome import send_welcome
from .models import DashboardCardImage, User


logger = logging.getLogger(__name__)

ACCOUNT_EXISTS = ("An account already exists with this email. Log in instead, or use "
                  "“Forgot your password?” on the log-in page to reset it.")


def _create_account(form):
    """Save a sign-up form's new account, or None with a friendly error on
    the form. The form already checks the email is free, but a sign-up
    sent twice (a double tap on a slow phone) can pass that check in both
    requests before either is saved: the second must say so, not crash."""
    from django.core.exceptions import ValidationError
    from django.db import IntegrityError, transaction

    try:
        with transaction.atomic():
            return form.save()
    except (ValidationError, IntegrityError) as error:
        logger.info("Sign-up refused at save: %s", error)
        form.add_error("email" if "email" in form.fields else None, ACCOUNT_EXISTS)
        return None


def _post_login_redirect(user):
    """Where someone lands right after signing in, based on role.

    Only the school app exists so far, so every non-admin role goes
    to the same holding dashboard for now — swapping it for the real
    teacher/student home later is a one-line change here.
    """
    if user.role == User.Role.SCHOOL_ADMIN:
        return "schools:dashboard"
    return "accounts:dashboard"


TOUR_DONE = "signup_tour_done"


def through_tour(view):
    """Sign-up pages are only reached through the welcome tour (/welcome/).
    Arriving any other way (a Get started button, a bookmarked or shared
    sign-up link) goes to the tour first, then on to the page asked for."""
    from functools import wraps
    from urllib.parse import urlencode

    from django.urls import reverse

    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if request.method == "GET" and not request.user.is_authenticated and not request.session.get(TOUR_DONE):
            return redirect(f"{reverse('landing:tour')}?{urlencode({'next': request.get_full_path()})}")
        return view(request, *args, **kwargs)
    return wrapped


def register_choice(request):
    """The hub: school, individual, or "I have a code from my school".

    Only the welcome tour's last button leads here (?welcomed=1). Every
    other visit — Get started, a sign-up link — goes through the tour first."""
    from django.utils.http import url_has_allowed_host_and_scheme

    if request.GET.get("welcomed") == "1":
        request.session[TOUR_DONE] = True
        wanted = request.GET.get("next", "")
        if wanted and url_has_allowed_host_and_scheme(wanted, allowed_hosts={request.get_host()}) and wanted.startswith("/"):
            return redirect(wanted)
        return render(request, "accounts/register_choice.html")
    if request.user.is_authenticated:
        return render(request, "accounts/register_choice.html")
    request.session.pop(TOUR_DONE, None)
    return redirect("landing:tour")


def _chosen_plan(form, audience):
    slug = form.cleaned_data.get("plan")
    return Plan.objects.filter(slug=slug, audience=audience, is_active=True).first() if slug else None


@through_tour
def register_school(request):
    if request.method == "POST":
        form = SchoolRegistrationForm(request.POST)
        user = _create_account(form) if form.is_valid() else None
        if user is not None:
            auth_login(request, user, backend="django.contrib.auth.backends.ModelBackend")
            send_welcome(request, user)
            plan = _chosen_plan(form, Plan.AUDIENCE_SCHOOL)
            if plan is not None:
                # Remembered now, trial or not: it sets how many teachers can join.
                subscription = subscription_for(user)
                if subscription is not None and subscription.plan_id is None:
                    subscription.plan = plan
                    subscription.save(update_fields=["plan", "updated_at"])
            messages.success(
                request,
                f"{user.school.name} is set up. Your school code is {user.school.code} — "
                "teachers and students both sign up with it.",
            )
            return redirect(begin_access(request, user, form.cleaned_data.get("start"), plan,
                                          form.cleaned_data.get("promo_code", "")))
    else:
        form = SchoolRegistrationForm()
    return render(request, "accounts/register_school.html", {"form": form})


@through_tour
def register_school_team(request):
    """Register a school, its admin, and the first teacher/student roster."""
    from io import BytesIO

    from django.conf import settings as dj_settings
    from django.db.models.functions import Lower
    from django.forms import formset_factory
    from django.http import FileResponse

    from .school_enrollment import MAX_TEAM_MEMBERS, SchoolEnrollmentConflict, create_school_team

    teacher_factory = formset_factory(
        SchoolTeamMemberForm, extra=0, max_num=MAX_TEAM_MEMBERS, validate_max=True,
        absolute_max=MAX_TEAM_MEMBERS + 5, can_delete=True,
    )
    student_factory = formset_factory(
        SchoolTeamMemberForm, extra=0, max_num=MAX_TEAM_MEMBERS, validate_max=True,
        absolute_max=MAX_TEAM_MEMBERS + 5, can_delete=True,
    )
    data = request.POST if request.method == "POST" else None
    form = SchoolTeamRegistrationForm(data)
    teachers = teacher_factory(data, prefix="teachers", form_kwargs={"kind": "teacher"})
    students = student_factory(data, prefix="students", form_kwargs={"kind": "student"})

    if request.method == "POST":
        form_valid = form.is_valid()
        teachers_valid = teachers.is_valid()
        students_valid = students.is_valid()
        valid = form_valid and teachers_valid and students_valid
        teacher_rows = [item.cleaned_data for item in teachers.forms
                        if item.cleaned_data and not item.cleaned_data.get("DELETE")]
        student_rows = [item.cleaned_data for item in students.forms
                        if item.cleaned_data and not item.cleaned_data.get("DELETE")]

        if len(teacher_rows) + len(student_rows) > MAX_TEAM_MEMBERS:
            form.add_error(None, f"Add up to {MAX_TEAM_MEMBERS} teachers and students in one registration.")

        email_fields = []
        if form.cleaned_data.get("admin_email"):
            email_fields.append((form, "admin_email", form.cleaned_data["admin_email"]))
        for formset in (teachers, students):
            for member_form in formset.forms:
                row = member_form.cleaned_data if member_form.is_bound else {}
                if row and not row.get("DELETE") and row.get("email"):
                    email_fields.append((member_form, "email", row["email"]))

        emails_seen = set()
        duplicated = set()
        for _owner, _field, email in email_fields:
            key = email.casefold()
            if key in emails_seen:
                duplicated.add(key)
            emails_seen.add(key)
        for owner, field_name, email in email_fields:
            if email.casefold() in duplicated:
                owner.add_error(field_name, "Use this email on one account only.")

        lookup_emails = list(emails_seen)
        if lookup_emails:
            existing_emails = {
                email.casefold()
                for email in User.objects.annotate(normalized_email=Lower("email"))
                .filter(normalized_email__in=lookup_emails).values_list("email", flat=True)
            }
            for owner, field_name, email in email_fields:
                if email.casefold() in existing_emails:
                    owner.add_error(field_name, "This email already belongs to an account.")

        plan = form.cleaned_data.get("plan")
        if plan is not None and plan.max_units is not None and len(teacher_rows) > plan.max_units:
            form.add_error("plan", f"This plan allows {plan.max_units} teachers; the roster has {len(teacher_rows)}.")

        valid = valid and not form.errors and not teachers.non_form_errors() and not students.non_form_errors()
        valid = valid and all(not item.errors for item in teachers.forms + students.forms)
        if valid:
            admin_data = {
                "first_name": form.cleaned_data["admin_first_name"],
                "last_name": form.cleaned_data["admin_last_name"],
                "email": form.cleaned_data["admin_email"],
            }
            site = getattr(dj_settings, "SITE_URL", "") or request.build_absolute_uri("/").rstrip("/")
            try:
                workbook, filename = create_school_team(
                    form.cleaned_data,
                    admin_data,
                    teacher_rows,
                    student_rows,
                    site_url=site,
                    plan=plan,
                )
            except SchoolEnrollmentConflict as error:
                form.add_error(None, str(error))
            else:
                # The school admin is welcomed; the team gets their logins on the sheet.
                send_welcome(request, User.objects.filter(email__iexact=admin_data["email"]).first())
                response = FileResponse(
                    BytesIO(workbook),
                    as_attachment=True,
                    filename=filename,
                    content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
                response["Cache-Control"] = "private, no-store, max-age=0"
                response["Pragma"] = "no-cache"
                response["X-Content-Type-Options"] = "nosniff"
                return response

    return render(request, "accounts/register_school_team.html", {
        "form": form,
        "teachers": teachers,
        "students": students,
        "max_team_members": MAX_TEAM_MEMBERS,
        "plan_available": form.fields["plan"].queryset.exists(),
    })


@through_tour
def register_individual(request):
    if request.method == "POST":
        form = IndividualRegistrationForm(request.POST)
        user = _create_account(form) if form.is_valid() else None
        if user is not None:
            auth_login(request, user, backend="django.contrib.auth.backends.ModelBackend")
            send_welcome(request, user)
            messages.success(request, "Welcome to Diction Masters!")
            return redirect(begin_access(request, user, form.cleaned_data.get("start"), _chosen_plan(form, Plan.AUDIENCE_INDIVIDUAL),
                                          form.cleaned_data.get("promo_code", "")))
    else:
        form = IndividualRegistrationForm()
    return render(request, "accounts/register_individual.html", {"form": form})


@through_tour
def register_student(request):
    if request.method == "POST":
        form = StudentRegistrationForm(request.POST)
        user = _create_account(form) if form.is_valid() else None
        if user is not None:
            auth_login(request, user, backend="django.contrib.auth.backends.ModelBackend")
            send_welcome(request, user)
            messages.success(request, f"Welcome, {user.first_name}! You're now part of {user.school.name}, and your school's plan covers you.")
            return redirect("accounts:dashboard")
    else:
        form = StudentRegistrationForm(initial={"school_code": request.GET.get("school", "")})
    return render(request, "accounts/register_student.html", {"form": form})


@through_tour
def join_with_code(request):
    if request.method == "POST":
        form = TeacherRegistrationForm(request.POST)
        user = _create_account(form) if form.is_valid() else None
        if user is not None:
            auth_login(request, user, backend="django.contrib.auth.backends.ModelBackend")
            send_welcome(request, user)
            messages.success(request, f"You're in, {user.first_name}. Welcome to {user.school.name}.")
            return redirect(_post_login_redirect(user))
    else:
        form = TeacherRegistrationForm(initial={"school_code": request.GET.get("school", "")})
    return render(request, "accounts/join_with_code.html", {"form": form})


class EmailLoginView(LoginView):
    template_name = "accounts/login.html"
    authentication_form = EmailAuthenticationForm
    redirect_authenticated_user = True

    def form_valid(self, form):
        # "Remember me on this device" unticked: leave it off the switcher.
        if not self.request.POST.get("remember_device"):
            self.request._dm_no_remember = True
        return super().form_valid(form)

    def get_initial(self):
        # Switching to an account that asks for its password: fill in who.
        initial = super().get_initial()
        if self.request.GET.get("as"):
            initial["username"] = self.request.GET["as"][:254]
        return initial

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Accounts already on this device: continue as one of them.
        context["device_accounts"] = [row.user for row in switcher.device_accounts(self.request)]
        context["adding"] = bool(self.request.GET.get("add"))
        return context

    def get_success_url(self):
        # Where they were heading before signing in — scanning a QR code on
        # a card, following a link — wins over the usual home page.
        wanted = self.get_redirect_url()
        return wanted or reverse_lazy(_post_login_redirect(self.request.user))


class EmailLogoutView(LogoutView):
    next_page = reverse_lazy("landing:home")


@require_POST
def switch_account(request):
    """Move to another account remembered on this device (the account
    switcher on the dashboard, or "Continue as" on the log-in page)."""
    try:
        wanted = int(request.POST.get("user", ""))
    except ValueError:
        wanted = 0
    row = switcher.find(request, wanted)
    if row is None:
        messages.error(request, "That account isn't on this device any more. Please sign in to it.")
        return redirect("accounts:login")
    if request.user.is_authenticated and request.user.pk == row.user_id:
        return redirect(_post_login_redirect(row.user))
    if row.needs_password:
        # An admin account (or a password changed since): stays on the
        # switcher, but its password is asked for every time.
        response = redirect(f"{reverse_lazy('accounts:login')}?as={quote(row.user.login_name)}")
        switcher.keep_current(request, response)
        if request.user.is_authenticated:
            auth_logout(request)
        name = row.user.get_full_name() or row.user.login_name
        why = "Admin accounts always ask for it." if row.user.is_staff or row.user.is_superuser else "Its password has changed."
        messages.info(request, f"Enter the password for {name} to switch to it. {why}")
        return response
    response = redirect(_post_login_redirect(row.user))
    switcher.keep_current(request, response)       # the account being left stays on the switcher
    auth_login(request, row.user, backend="django.contrib.auth.backends.ModelBackend")
    messages.success(request, f"Switched to {row.user.get_full_name() or row.user.login_name}.")
    return response


@require_POST
def add_account(request):
    """Sign another account in on this device, keeping the ones already
    remembered: the current one is signed out, then the log-in page."""
    response = redirect(f"{reverse_lazy('accounts:login')}?add=1")
    switcher.keep_current(request, response)       # the account being left stays on the switcher
    if request.user.is_authenticated:
        auth_logout(request)
    return response


@require_POST
def remove_account(request):
    """Take an account off this device's switcher. It isn't signed out if
    it's the one in use; it just won't be offered for switching."""
    try:
        wanted = int(request.POST.get("user", ""))
    except ValueError:
        wanted = 0
    back = request.POST.get("next") or ""
    response = redirect(back if back.startswith("/") and not back.startswith("//") else "accounts:dashboard")
    row = switcher.find(request, wanted)
    switcher.forget(request, response, wanted)
    if row is not None:
        messages.success(request, f"{row.user.get_full_name() or row.user.login_name} was removed from this device.")
    return response


@require_POST
def forget_accounts(request):
    """Take every account off this device and sign out: for handing a
    device on, or a shared computer."""
    if request.user.is_authenticated:
        auth_logout(request)
    response = redirect("accounts:login")
    switcher.forget(request, response)
    messages.success(request, "Every account was removed from this device.")
    return response


@login_required(login_url="accounts:login")
def delete_account(request):
    """Delete your own account and everything saved with it.

    Required by the App Store and Google Play for any app where people can
    sign up. The school itself stays (other teachers and students use it);
    payment records are kept for the accounts, without the person attached.
    Staff accounts are removed from the control room instead."""
    user = request.user
    error = ""
    if request.method == "POST":
        if user.is_staff or user.is_superuser:
            error = "Staff accounts are removed from the control room, not here."
        elif not user.check_password(request.POST.get("password", "")):
            error = "That password isn't right. Please try again."
        else:
            auth_logout(request)
            user.delete()
            messages.success(request, "Your account and everything saved with it have been deleted.")
            response = redirect("landing:home")
            # Also wipe anything this device kept for offline use.
            response["Clear-Site-Data"] = '"cache", "storage"'
            return response
    return render(request, "accounts/delete_account.html", {"error": error})


@login_required(login_url="accounts:login")
def dashboard(request):
    """The learner's home: streak, progress across every tool, where to
    carry on, and the tools themselves."""
    if request.user.role == User.Role.SCHOOL_ADMIN:
        return redirect("schools:dashboard")
    dashboard = learner_dashboard(request.user)
    dashboard["dashboard_card_images"] = {
        card.key.replace("-", "_"): card.image.url
        for card in DashboardCardImage.objects.exclude(image="")
        if card.image
    }
    dashboard["switcher"] = switcher.context(request)
    return render(request, "accounts/dashboard.html", dashboard)
