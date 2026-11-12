"""
The offline computer app, in /admin/:

    Unlocked computers  "Add" = unlock a computer with no internet: type the
                        number it shows, choose the level and end date, and
                        send back the code it gives (unlock.py)
    Activation codes    make codes, see which computers use each one, free a
                        seat (tick "revoked" on that computer), stop a code
    Lessons releases    "Add" builds a new release of every lesson (or some
                        levels) in the background; installed apps pick it up
                        the next time they're online
"""

import subprocess
import sys
from pathlib import Path

from django import forms
from django.conf import settings
from django.contrib import admin, messages

from apps.echospell.models import LEVEL_NAME_CHOICES

from . import unlock
from .models import Activation, ActivationCode, ComputerUnlock, ContentRelease, new_code


def start_build(release):
    """Run the build in its own process, which carries on after this request."""
    subprocess.Popen(
        [sys.executable, str(Path(settings.BASE_DIR) / "manage.py"), "export_desktop_content", "--release", str(release.pk)],
        cwd=settings.BASE_DIR, start_new_session=True,
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


class LevelsField(forms.MultipleChoiceField):
    widget = forms.CheckboxSelectMultiple

    def __init__(self, **kwargs):
        super().__init__(choices=LEVEL_NAME_CHOICES, required=False,
                         help_text="Tick none for every level.", **kwargs)


class ActivationCodeForm(forms.ModelForm):
    level_choice = LevelsField(label="Levels")
    how_many = forms.IntegerField(min_value=1, max_value=500, initial=1, required=False,
                                  help_text="When adding: make this many codes at once, all the same.")

    class Meta:
        model = ActivationCode
        fields = ["holder", "level_choice", "seats", "valid_until", "is_active", "notes"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["level_choice"].initial = self.instance.level_list
        if self.instance.pk:
            del self.fields["how_many"]

    def save(self, commit=True):
        self.instance.set_levels(self.cleaned_data["level_choice"])
        return super().save(commit)


class ActivationInline(admin.TabularInline):
    model = Activation
    extra = 0
    fields = ["device_name", "learner_name", "system", "app_version", "content_release", "activated_at", "last_seen", "revoked"]
    readonly_fields = ["device_name", "learner_name", "system", "app_version", "content_release", "activated_at", "last_seen"]
    can_delete = True
    verbose_name_plural = "Computers using this code (tick Revoked to free a seat)"


@admin.register(ActivationCode)
class ActivationCodeAdmin(admin.ModelAdmin):
    form = ActivationCodeForm
    list_display = ["code", "holder", "levels_label", "seats_used", "seats", "valid_until", "is_active", "created_at"]
    list_filter = ["is_active"]
    search_fields = ["code", "holder", "notes", "activations__device_name", "activations__learner_name"]
    readonly_fields = ["code", "created_at"]
    inlines = [ActivationInline]

    def get_fields(self, request, obj=None):
        fields = ["holder", "level_choice", "seats", "valid_until", "is_active", "notes"]
        return (["code", *fields, "created_at"] if obj else [*fields, "how_many"])

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        extra = (form.cleaned_data.get("how_many") or 1) - 1 if not change else 0
        made = [obj.code]
        for _ in range(extra):
            copy = ActivationCode(code=new_code(), holder=obj.holder, levels=obj.levels, seats=obj.seats,
                                  valid_until=obj.valid_until, is_active=obj.is_active, notes=obj.notes)
            copy.save()
            made.append(copy.code)
        if extra:
            messages.success(request, f"{len(made)} codes made for {obj.holder}: " + ", ".join(made))


@admin.register(ContentRelease)
class ContentReleaseAdmin(admin.ModelAdmin):
    list_display = ["__str__", "status", "progress", "pages", "files", "size_mb", "new_mb", "created_at", "finished_at"]
    readonly_fields = ["status", "manifest", "pages", "files", "size", "new_size", "progress", "skipped", "error",
                       "created_at", "finished_at"]
    fields = ["levels", "include_videos", *readonly_fields]

    @admin.display(description="Size (MB)")
    def size_mb(self, obj):
        return round(obj.size / 1048576)

    @admin.display(description="New (MB)")
    def new_mb(self, obj):
        return round(obj.new_size / 1048576)

    def has_change_permission(self, request, obj=None):
        return obj is None

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        if not change:
            start_build(obj)
            messages.info(request, "The release is building in the background. Refresh this list to follow it.")


class ComputerUnlockForm(forms.ModelForm):
    computer = forms.CharField(label="Computer number", max_length=12,
                               help_text="As the computer shows it, e.g. K7QX-3MPA. A wrong character is caught.")

    class Meta:
        model = ComputerUnlock
        fields = ["computer", "level", "valid_until", "holder", "notes", "revoked"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            self.initial["computer"] = self.instance.computer_label

    def clean_computer(self):
        number = unlock.clean_computer(self.cleaned_data["computer"])
        if not number:
            raise forms.ValidationError("That isn't a computer number: check each character with the school.")
        return number

    def clean(self):
        data = super().clean()
        try:
            if data.get("computer") and data.get("level"):
                unlock.make_code(data["computer"], data["level"], data.get("valid_until"))
        except ValueError as error:
            raise forms.ValidationError(str(error))
        return data


@admin.register(ComputerUnlock)
class ComputerUnlockAdmin(admin.ModelAdmin):
    form = ComputerUnlockForm
    list_display = ["computer_label", "level", "holder", "valid_until", "code", "revoked", "last_seen", "created_at"]
    list_filter = ["level", "revoked"]
    search_fields = ["computer", "holder", "code", "notes"]
    readonly_fields = ["code", "created_by", "created_at", "last_seen"]

    @admin.display(description="Computer", ordering="computer")
    def computer_label(self, obj):
        return obj.computer_label

    def get_fields(self, request, obj=None):
        fields = ["computer", "level", "valid_until", "holder", "notes"]
        return ["code", *fields, "revoked", "created_by", "created_at", "last_seen"] if obj else fields

    def save_model(self, request, obj, form, change):
        obj.code = unlock.make_code(obj.computer, obj.level, obj.valid_until)
        if not change:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)
        until = f"until {obj.valid_until:%d %B %Y}" if obj.valid_until else "with no end date"
        messages.success(request, f"Unlock code for computer {obj.computer_label} ({obj.level}, {until}): {obj.code}")
