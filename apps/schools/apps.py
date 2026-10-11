from django.apps import AppConfig


class SchoolsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.schools"
    label = "schools"
    verbose_name = "Schools"

    def ready(self):
        from django.db.models.signals import m2m_changed

        from .models import SchoolClass

        def teachers_changed(sender, instance, action, reverse, pk_set, **kwargs):
            # A teacher's levels follow the classes they teach (apps/schools/classes.py).
            if action not in ("post_add", "post_remove", "post_clear"):
                return
            from .classes import sync_teachers

            if reverse:                              # teacher.teaching_classes changed
                sync_teachers([instance.pk])
            else:                                    # school_class.teachers changed
                sync_teachers(pk_set or [])

        m2m_changed.connect(teachers_changed, sender=SchoolClass.teachers.through,
                            dispatch_uid="schools.teachers_changed")
