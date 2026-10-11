"""Grade names for school people in templates: {% load grades %}, then
{{ level|level_name:user }} shows "Grade 3" to someone at a school and
"Level 3" to an individual learner (apps/schools/grades.py)."""

from django import template

from apps.schools.grades import label_for_level

register = template.Library()


@register.filter
def level_name(level, user=None):
    if not level:
        return level
    if user is None or getattr(user, "school_id", None):
        return label_for_level(level)
    return level
