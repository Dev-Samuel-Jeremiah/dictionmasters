from django.contrib import messages
from django.shortcuts import redirect, render

from apps.accounts.decorators import role_required
from apps.accounts.models import User

from .forms import GenerateAccessCodeForm


@role_required(User.Role.SCHOOL_ADMIN)
def dashboard(request):
    school = request.user.school

    if request.method == "POST":
        form = GenerateAccessCodeForm(request.POST)
        if form.is_valid():
            code = school.access_codes.create(
                role=form.cleaned_data["role"],
                level=form.cleaned_data["level"],
                label=form.cleaned_data["label"],
                created_by=request.user,
            )
            messages.success(
                request,
                f"New {code.get_role_display().lower()} code for {code.level}: {code.code}. "
                "Share it with them to join.",
            )
            return redirect("schools:dashboard")
    else:
        form = GenerateAccessCodeForm()

    codes = school.access_codes.select_related("used_by").all()

    context = {
        "school": school,
        "form": form,
        "teachers": school.teachers,
        "students": school.students,
        "pending_codes": codes.filter(used_by__isnull=True),
        "redeemed_codes": codes.filter(used_by__isnull=False),
    }
    return render(request, "schools/dashboard.html", context)
