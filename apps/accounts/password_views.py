"""
Passwords: forgotten (emailed link, or the school admin is asked), reset
from the link, and changed by someone signed in. The work is in
apps/accounts/password_reset.py.

    /accounts/password/forgot/                    ask for help
    /accounts/password/forgot/sent/               what happens next
    /accounts/password/reset/<uid>/<token>/       choose a new password
    /accounts/password/change/                    signed in: change it
"""

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordChangeForm, SetPasswordForm
from django.contrib.auth.views import PasswordChangeView, PasswordResetConfirmView
from django.shortcuts import redirect, render
from django.urls import reverse

from . import password_reset
from .forms import PASSWORD_HELP, StyledFormMixin


class ForgotForm(StyledFormMixin, forms.Form):
    who = forms.CharField(
        label="Email or username", max_length=254,
        widget=forms.TextInput(attrs={"autocomplete": "username", "autocapitalize": "none", "autofocus": True}),
        help_text="The one you use to log in.",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._style_fields()


class NewPasswordForm(StyledFormMixin, SetPasswordForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["new_password1"].label = "New password"
        self.fields["new_password1"].help_text = PASSWORD_HELP
        self.fields["new_password2"].label = "Type it again"
        self.fields["new_password2"].help_text = ""
        for name in ("new_password1", "new_password2"):
            self.fields[name].widget.attrs["autocomplete"] = "new-password"
        self._style_fields()


class ChangeForm(StyledFormMixin, PasswordChangeForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["old_password"].label = "Current password"
        self.fields["new_password1"].label = "New password"
        self.fields["new_password1"].help_text = PASSWORD_HELP
        self.fields["new_password2"].label = "Type the new one again"
        self.fields["new_password2"].help_text = ""
        self._style_fields()


def forgot(request):
    if request.user.is_authenticated:
        return redirect("accounts:password_change")
    form = ForgotForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        if password_reset.address_over_limit(request):
            form.add_error(None, "That's a lot of requests from here. Please wait an hour and try again.")
        else:
            password_reset.start(request, form.cleaned_data["who"])
            return redirect("accounts:password_forgot_sent")
    return render(request, "accounts/password_forgot.html", {"form": form})


def forgot_sent(request):
    return render(request, "accounts/password_forgot_sent.html")


def _home_for(user):
    from .views import _post_login_redirect

    return reverse(_post_login_redirect(user))


class ResetConfirm(PasswordResetConfirmView):
    template_name = "accounts/password_reset_confirm.html"
    form_class = NewPasswordForm
    post_reset_login = True
    post_reset_login_backend = "django.contrib.auth.backends.ModelBackend"

    def form_valid(self, form):
        response = super().form_valid(form)
        user = form.user
        user.device_logins.all().delete()           # off every other device; this one is remembered again
        password_reset.resolve(user)
        messages.success(self.request, "Your new password is set, and you're logged in.")
        return response

    def get_success_url(self):
        return _home_for(self.user)


class Change(PasswordChangeView):
    template_name = "accounts/password_change.html"
    form_class = ChangeForm

    def form_valid(self, form):
        response = super().form_valid(form)            # keeps this session signed in
        user = form.user
        user.device_logins.all().delete()
        self.request._dm_remember = user                # this device stays on the switcher
        password_reset.resolve(user, by=user)
        messages.success(self.request, "Your password is changed. Use the new one next time you log in.")
        return response

    def get_success_url(self):
        return _home_for(self.request.user)


reset_confirm = ResetConfirm.as_view()
change = login_required(Change.as_view())
