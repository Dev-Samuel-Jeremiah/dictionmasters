"""Small helpers for restricting a view to certain user roles."""

from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect


def role_required(*roles):
    """Only let signed-in users with one of `roles` through.

    Usage: @role_required(User.Role.SCHOOL_ADMIN)
    """

    def decorator(view_func):
        @wraps(view_func)
        @login_required(login_url="accounts:login")
        def wrapped(request, *args, **kwargs):
            if request.user.role not in roles:
                messages.error(request, "You don't have access to that page.")
                return redirect("landing:home")
            return view_func(request, *args, **kwargs)

        return wrapped

    return decorator
