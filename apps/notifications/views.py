"""
The bell (templates/includes/header.html, static/js/notifications.js):

    page       /notifications/: everything, reminders first (marks updates read)
    panel      the bell's dropdown, as HTML (marks what it shows read)
    count      {"count": n} for the bell's badge, polled every minute
    open       one update: marked read, then on to where it leads
    read_all   mark every update read
"""

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from . import reminders
from .models import Notification

PANEL_UPDATES = 8


def badge_count(user):
    """Unread updates plus things still to do."""
    return Notification.objects.filter(user=user, read_at__isnull=True).count() + len(reminders.for_user(user))


def _mark_read(user, pks):
    if pks:
        Notification.objects.filter(user=user, pk__in=pks, read_at__isnull=True).update(read_at=timezone.now())


@login_required
def page(request):
    updates = list(request.user.notifications.all()[:100])
    response = render(request, "notifications/page.html", {
        "todo": reminders.for_user(request.user), "updates": updates,
    })
    _mark_read(request.user, [n.pk for n in updates if n.is_unread])
    return response


@login_required
def panel(request):
    updates = list(request.user.notifications.all()[:PANEL_UPDATES])
    response = render(request, "notifications/_panel.html", {
        "todo": reminders.for_user(request.user), "updates": updates,
        "more": request.user.notifications.count() > PANEL_UPDATES,
    })
    _mark_read(request.user, [n.pk for n in updates if n.is_unread])
    return response


@login_required
def count(request):
    return JsonResponse({"count": badge_count(request.user)})


@login_required
def open_one(request, pk):
    found = get_object_or_404(Notification, pk=pk, user=request.user)
    _mark_read(request.user, [found.pk])
    if found.url and url_has_allowed_host_and_scheme(found.url, allowed_hosts={request.get_host()}):
        return redirect(found.url)
    return redirect("notifications:page")


@login_required
@require_POST
def read_all(request):
    request.user.notifications.filter(read_at__isnull=True).update(read_at=timezone.now())
    return redirect("notifications:page")
