from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.accounts.decorators import role_required
from apps.accounts.models import User

from .forms import LibraryItemForm
from .models import LibraryItem


def visible_items(user):
    items = LibraryItem.objects.filter(is_published=True)
    if user.school_id:
        return items.filter(Q(school__isnull=True) | Q(school_id=user.school_id))
    return items.filter(school__isnull=True)


@login_required
def hub(request):
    items = visible_items(request.user)
    query = request.GET.get("q", "").strip()
    kind = request.GET.get("kind", "").strip()
    if query:
        items = items.filter(Q(title__icontains=query) | Q(summary__icontains=query) | Q(description__icontains=query))
    if kind in LibraryItem.Kind.values:
        items = items.filter(kind=kind)
    return render(request, "diction_library/hub.html", {
        "items": items.select_related("school"),
        "query": query,
        "selected_kind": kind,
        "kinds": LibraryItem.Kind.choices,
    })


@login_required
def item_detail(request, slug):
    item = get_object_or_404(visible_items(request.user).select_related("school"), slug=slug)
    return render(request, "diction_library/item_detail.html", {"item": item})


@role_required(User.Role.SCHOOL_ADMIN)
def manage(request):
    if not request.user.school_id:
        messages.error(request, "Your account is not linked to a school.")
        return redirect("schools:dashboard")
    items = LibraryItem.objects.filter(school=request.user.school).order_by("-created_at")
    return render(request, "diction_library/manage.html", {"items": items})


@role_required(User.Role.SCHOOL_ADMIN)
def edit_item(request, pk=None):
    if not request.user.school_id:
        messages.error(request, "Your account is not linked to a school.")
        return redirect("schools:dashboard")
    instance = get_object_or_404(LibraryItem, pk=pk, school=request.user.school) if pk else None
    if request.method == "POST":
        form = LibraryItemForm(request.POST, request.FILES, instance=instance)
        if form.is_valid():
            item = form.save(commit=False)
            item.school = request.user.school
            item.created_by = item.created_by or request.user
            item.save()
            messages.success(request, f"{item.title} has been saved to your school's library.")
            return redirect("diction_library:manage")
    else:
        form = LibraryItemForm(instance=instance)
    return render(request, "diction_library/edit.html", {"form": form, "item": instance})


@role_required(User.Role.SCHOOL_ADMIN)
@require_POST
def delete_item(request, pk):
    item = get_object_or_404(LibraryItem, pk=pk, school=request.user.school)
    title = item.title
    item.delete()
    messages.success(request, f"{title} has been removed from your school's library.")
    return redirect("diction_library:manage")
