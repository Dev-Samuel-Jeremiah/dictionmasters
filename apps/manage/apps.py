from django.apps import AppConfig


class ManageConfig(AppConfig):
    """The Diction Masters control room: a plain-English admin area for
    the people who run the platform, separate from the Django admin."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.manage"
    label = "manage"
    verbose_name = "Control room"

    def ready(self):
        # Use the shared editor for learner-facing Django Admin text fields.
        # The check runs per model, so structured or tokenized text (see
        # PLAIN_TEXT_MODEL_FIELDS) keeps a plain textarea in every admin.
        from django.contrib.admin.options import BaseModelAdmin
        from django.contrib.admin.widgets import AdminTextareaWidget
        from django.db import models

        from apps.manage.rich_text import RichTextWidget, is_rich_text_field

        if getattr(BaseModelAdmin.formfield_for_dbfield, "_rich_text", False):
            return
        original = BaseModelAdmin.formfield_for_dbfield

        def formfield_for_dbfield(admin, db_field, request, **kwargs):
            formfield = original(admin, db_field, request, **kwargs)
            if (
                formfield is not None
                and isinstance(db_field, models.TextField)
                and type(formfield.widget) is AdminTextareaWidget
                and is_rich_text_field(db_field.name, db_field.model)
            ):
                formfield.widget = RichTextWidget(attrs=formfield.widget.attrs)
            return formfield

        formfield_for_dbfield._rich_text = True
        BaseModelAdmin.formfield_for_dbfield = formfield_for_dbfield
