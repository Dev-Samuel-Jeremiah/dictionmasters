from django.shortcuts import render
from django.urls import reverse

from apps.accounts.decorators import role_required
from apps.accounts.models import User


@role_required(User.Role.SCHOOL_ADMIN)
def dashboard(request):
    """The school admin's page. Teachers and students both sign up with the
    school code; the school's plan sets how many teachers can join."""
    school = request.user.school
    codes = school.access_codes.select_related("used_by").all()
    context = {
        "school": school,
        "plan": school.chosen_plan(),
        "teacher_link": request.build_absolute_uri(reverse("accounts:join_with_code")) + f"?school={school.code}",
        "teachers": school.teachers,
        "students": school.students,
        "pending_codes": codes.filter(used_by__isnull=True, role="teacher"),
    }
    return render(request, "schools/dashboard.html", context)
