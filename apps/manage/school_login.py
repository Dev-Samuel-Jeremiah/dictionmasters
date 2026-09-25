"""The "School login" fields on the control room's school form: the school
admin account a school signs in with on the main site's login page. Creating
a school here makes that account; editing it changes the email, the name or
the password (left blank, the password stays as it is)."""

from django import forms
from django.contrib.auth import password_validation

NAME, EMAIL, PASSWORD, CONFIRM = "login_name", "login_email", "login_password", "login_password2"


def school_admin(school):
    if school is None or not school.pk:
        return None
    return school.members.filter(role="school_admin").order_by("date_joined").first()


def add_login_fields(form, school):
    admin = school_admin(school)
    new = admin is None
    keep = "" if new else " Leave blank to keep their current password."
    form.fields[NAME] = forms.CharField(
        label="School login: admin's name", max_length=150, required=False,
        initial=admin.get_full_name() if admin else "",
        help_text="The person who manages this school on Diction Masters.",
    )
    form.fields[EMAIL] = forms.EmailField(
        label="School login: email", required=False, initial=admin.email if admin else "",
        help_text="They sign in with this email on the main site's Log in page, then add teachers and share the school code.",
    )
    form.fields[PASSWORD] = forms.CharField(
        label="School login: password", required=False, strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}, render_value=False),
        help_text="At least 8 characters, not just numbers." + keep,
    )
    form.fields[CONFIRM] = forms.CharField(
        label="School login: confirm password", required=False, strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}, render_value=False),
    )
    for name in (NAME, EMAIL, PASSWORD, CONFIRM):
        form.fields[name].widget.attrs["class"] = "cr-input"


def check_login(form, school):
    """After form.is_valid(). Adds errors and returns False if the login
    details can't be saved."""
    from apps.accounts.models import User

    admin = school_admin(school)
    data = form.cleaned_data
    name = (data.get(NAME) or "").strip()
    email = (data.get(EMAIL) or "").lower().strip()
    password, confirm = data.get(PASSWORD) or "", data.get(CONFIRM) or ""
    ok = True

    if admin is None:
        if not email:
            form.add_error(EMAIL, "Give the email the school will sign in with.")
            ok = False
        if not name:
            form.add_error(NAME, "Give the name of the person who manages this school.")
            ok = False
        if not password:
            form.add_error(PASSWORD, "Set a password so the school can sign in.")
            ok = False
    elif not email:
        form.add_error(EMAIL, "The school needs a login email.")
        ok = False

    if email and User.objects.filter(email=email).exclude(pk=getattr(admin, "pk", None)).exists():
        form.add_error(EMAIL, "Another account already uses this email.")
        ok = False
    if password:
        if password != confirm:
            form.add_error(CONFIRM, "Those passwords don't match.")
            ok = False
        else:
            try:
                password_validation.validate_password(password, admin)
            except forms.ValidationError as error:
                form.add_error(PASSWORD, error)
                ok = False
    return ok


def save_login(school, form):
    """Returns a short note of what changed, for the success message."""
    from apps.accounts.models import User

    data = form.cleaned_data
    name = (data.get(NAME) or "").strip()
    first, _, last = name.partition(" ")
    email = (data.get(EMAIL) or "").lower().strip()
    password = data.get(PASSWORD) or ""
    admin = school_admin(school)

    if admin is None:
        User.objects.create_user(
            email=email, password=password, first_name=first, last_name=last.strip(),
            role=User.Role.SCHOOL_ADMIN, school=school,
        )
        return f"School login created: {email}."

    changed = []
    if email and email != admin.email:
        admin.email = email
        changed.append("email")
    if name and name != admin.get_full_name():
        admin.first_name, admin.last_name = first, last.strip()
        changed.append("name")
    if password:
        admin.set_password(password)
        changed.append("password")
    if changed:
        admin.save()
        return f"School login updated ({', '.join(changed)})."
    return ""
