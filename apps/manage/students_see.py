"""
The control room's What students see page: every course and tool on the
Learn page against every grade, with a tick where that grade's students
may open it.

A tick means the grade's content level (Grade 3 is Level 3; Pre-School
is Pre-Level) may use the tool; it's saved as the tool's levels
(learning_tools.ToolLevels), the rule apps.accounts.access.can_use_tool
applies everywhere: Learn, search, menus and the tool's own pages. Every
box ticked removes the limit. Only students are held back: teachers,
staff and individual learners always see everything.
"""

from django.contrib import messages
from django.shortcuts import redirect, render

from apps.accounts.access import pack_levels, unpack_levels
from apps.echospell.models import LEVEL_NAME_CHOICES
from apps.learning_tools.models import ToolLevels
from apps.learning_tools.views import TOOLS
from apps.schools.grades import label_for_level

from .views import _base_context, staff_only

LEVELS = [value for value, _label in LEVEL_NAME_CHOICES]


def _tools():
    """The tools a student could be given: every Learn tool but teachers' own."""
    return [t for t in TOOLS if not t.get("teachers")]


@staff_only
def students_see(request):
    tools = _tools()
    rows = {row.tool: row for row in ToolLevels.objects.all()}

    if request.method == "POST":
        closed = []
        for tool in tools:
            name = tool["url_name"]
            chosen = [lvl for lvl in LEVELS if f"{name}|{lvl}" in request.POST]
            if not chosen:
                closed.append(tool["name"])
                continue
            if len(chosen) == len(LEVELS):
                ToolLevels.objects.filter(tool=name).delete()           # open to every grade
            else:
                ToolLevels.objects.update_or_create(tool=name, defaults={"levels": pack_levels(chosen)})
        if closed:
            messages.error(request, "Keep at least one grade ticked for " + ", ".join(closed)
                                    + ". Those weren't changed.")
        else:
            messages.success(request, "Saved. Students see the change on their next page.")
        return redirect("manage:students_see")

    columns = [{"level": lvl, "label": label_for_level(lvl)} for lvl in LEVELS]
    table = []
    for tool in tools:
        kept = unpack_levels(rows[tool["url_name"]].levels) if tool["url_name"] in rows else []
        table.append({
            "tool": tool, "limited": bool(kept),
            "cells": [{"level": col["level"], "label": col["label"], "open": not kept or col["level"] in kept}
                      for col in columns],
        })
    return render(request, "manage/students_see.html", _base_context(
        request, "students-see", columns=columns, table=table,
    ))
