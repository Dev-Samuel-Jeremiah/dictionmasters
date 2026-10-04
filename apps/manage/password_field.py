"""The "Set a new password" field on the control room's user form: staff
can give anyone a new password (a learner who forgot theirs and has no
email, say). Left blank, the password stays as it is. Setting one answers
that person's password help requests and signs them out of other devices."""

from django import forms

FIELD = "set_password"


def add_password_field(form, obj):
    form.fields[FIELD] = forms.CharField(
        label="Set a new password", required=False, strip=False, min_length=6,
        widget=forms.TextInput(attrs={"autocomplete": "off", "placeholder": "Leave blank to keep their password"}),
        help_text="Type a new password to replace theirs, then tell them what it is. "
                  "Their current password can't be shown.",
    )


def save_password(form, saved, by=None):
    from apps.accounts.password_reset import resolve

    password = form.cleaned_data.get(FIELD) or ""
    if not password:
        return False
    saved.set_password(password)
    saved.save(update_fields=["password", "encrypted_login_password"])
    saved.device_logins.all().delete()
    resolve(saved, by=by)
    return True
