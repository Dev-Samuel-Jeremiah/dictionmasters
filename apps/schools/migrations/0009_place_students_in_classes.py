"""Every existing school student into a class, with nothing lost.

For each school, one class per grade its students and teachers are on
(a Level 3 student goes into "Primary 3", Pre-Level into "Kindergarten"),
in the newest school year. Students are placed in their level's class;
teachers join the classes of all their levels, and a class with just one
teacher gets them as its class teacher. Schools rename or split classes
afterwards. Levels themselves are left exactly as they were."""

from collections import defaultdict

from django.db import migrations

# A copy of apps/schools/grades.py's default grade per level, as it was
# when this migration was written.
GRADE_FOR_LEVEL = {
    "Pre-Level": "kindergarten",
    **{f"Level {n}": f"primary_{n}" for n in range(1, 7)},
    **{f"Level {n + 6}": f"jss_{n}" for n in range(1, 4)},
    **{f"Level {n + 9}": f"sss_{n}" for n in range(1, 4)},
}


def forwards(apps, schema_editor):
    User = apps.get_model("accounts", "User")
    SchoolClass = apps.get_model("schools", "SchoolClass")
    Session = apps.get_model("scheme", "Session")
    session = Session.objects.order_by("-name").first()
    classes = {}

    def class_for(school_id, level):
        key = (school_id, level)
        if key not in classes:
            classes[key] = SchoolClass.objects.get_or_create(
                school_id=school_id, session=session, grade=GRADE_FOR_LEVEL[level], name="")[0]
        return classes[key]

    placed = []
    for student in (User.objects.filter(role="student", school__isnull=False, school_class__isnull=True)
                    .only("pk", "school_id", "level").iterator()):
        if student.level in GRADE_FOR_LEVEL:
            student.school_class_id = class_for(student.school_id, student.level).pk
            placed.append(student)
    User.objects.bulk_update(placed, ["school_class"], batch_size=500)

    Through = SchoolClass.teachers.through
    pairs, by_class = [], defaultdict(list)
    for teacher in (User.objects.filter(role="teacher", school__isnull=False)
                    .only("pk", "school_id", "level", "additional_levels").iterator()):
        levels = [teacher.level] + [lvl for lvl in teacher.additional_levels.strip(",").split(",") if lvl]
        for level in dict.fromkeys(levels):
            if level in GRADE_FOR_LEVEL:
                found = class_for(teacher.school_id, level)
                pairs.append(Through(schoolclass_id=found.pk, user_id=teacher.pk))
                by_class[found.pk].append(teacher.pk)
    Through.objects.bulk_create(pairs, ignore_conflicts=True, batch_size=500)
    for class_pk, teacher_pks in by_class.items():
        if len(teacher_pks) == 1:
            SchoolClass.objects.filter(pk=class_pk, class_teacher__isnull=True).update(class_teacher_id=teacher_pks[0])


def backwards(apps, schema_editor):
    User = apps.get_model("accounts", "User")
    SchoolClass = apps.get_model("schools", "SchoolClass")
    User.objects.filter(school_class__isnull=False).update(school_class=None)
    SchoolClass.objects.all().delete()


class Migration(migrations.Migration):
    dependencies = [
        ("schools", "0008_schoolclass"),
        ("accounts", "0014_user_school_class"),
        ("scheme", "0005_scheme_entry_cards"),
    ]

    operations = [migrations.RunPython(forwards, backwards)]
