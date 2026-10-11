"""
The updates that something happening makes (apps/notifications/notify.py).

    a test handed in for marking   -> the pupil's teachers
    a test marked by a teacher     -> the pupil: results back
    a recording reviewed           -> the pupil: their recording was marked
    a report card published        -> the pupil
    a CA test or exam published    -> every school pupil on its level
    a pupil or teacher joining     -> the class's teachers and the school's admins
    a password help request        -> the school's admins

Each works out what changed by keeping the old status on the instance
(pre_save), so an update is made once, when it happens.
"""

from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from django.urls import reverse
from django.utils.formats import date_format
from django.utils.timezone import localtime

from .models import Notification
from .notify import admins_of, name_of, notify, notify_many, teachers_of

K = Notification.Kind


def _remember(sender, instance, fields):
    """Keep the saved values of `fields` on the instance, for post_save."""
    old = sender.objects.filter(pk=instance.pk).values(*fields).first() if instance.pk else None
    instance._before = old or {}


# --------------------------------------------------------------- assessments

@receiver(pre_save, sender="assessments.Attempt", dispatch_uid="notif-attempt-pre")
def _attempt_before(sender, instance, **kwargs):
    _remember(sender, instance, ["status"])


@receiver(post_save, sender="assessments.Attempt", dispatch_uid="notif-attempt-post")
def _attempt_after(sender, instance, created, **kwargs):
    before = getattr(instance, "_before", {}).get("status")
    if instance.status == before:
        return
    student, test = instance.user, instance.assessment
    if instance.status == sender.Status.AWAITING:
        notify_many(teachers_of(student), K.TO_MARK, f"{name_of(student)} handed in {test.title}",
                    "Spoken or written answers are waiting for you to mark.",
                    reverse("assessments:mark", args=[instance.pk]), key=f"to-mark-{instance.pk}")
    elif instance.status == sender.Status.MARKED:
        notify(student, K.RESULT, f"Your {test.title} is marked", f"You scored {instance.percent}%.",
               reverse("assessments:result", args=[instance.pk]), key=f"result-{instance.pk}")


@receiver(pre_save, sender="assessments.Assessment", dispatch_uid="notif-test-pre")
def _test_before(sender, instance, **kwargs):
    _remember(sender, instance, ["is_published"])


@receiver(post_save, sender="assessments.Assessment", dispatch_uid="notif-test-post")
def _test_after(sender, instance, created, **kwargs):
    """A school CA test or exam just published: tell its level's school pupils."""
    if not (instance.is_published and instance.kind in ("ca", "exam") and instance.level):
        return
    if not created and getattr(instance, "_before", {}).get("is_published"):
        return                                     # already published before
    from apps.accounts.models import User

    pupils = User.objects.filter(role=User.Role.STUDENT, is_active=True, school__isnull=False,
                                 level=instance.level).values_list("pk", flat=True)
    when = f" It opens on {date_format(localtime(instance.opens_at), 'l j F')}." if instance.opens_at else ""
    notify_many(pupils, K.TEST, f"New test: {instance.title}", f"For your class.{when}",
                reverse("assessments:detail", args=[instance.slug]), key=f"test-open-{instance.pk}")


# ---------------------------------------------------------------- EchoSpell

@receiver(pre_save, sender="echospell.ActivityAttempt", dispatch_uid="notif-activity-pre")
def _activity_before(sender, instance, **kwargs):
    _remember(sender, instance, ["status"])


@receiver(post_save, sender="echospell.ActivityAttempt", dispatch_uid="notif-activity-post")
def _activity_after(sender, instance, created, **kwargs):
    if instance.status != sender.STATUS_REVIEWED or getattr(instance, "_before", {}).get("status") == sender.STATUS_REVIEWED:
        return
    activity = instance.activity
    group = activity.group
    url = reverse("echospell:activity_result", args=[group.level.slug, group.slug, activity.slug, instance.pk])
    notify(instance.user, K.RESULT, f"Your recording for {activity.title} was marked",
           "See what your teacher said.", url, key=f"reviewed-{instance.pk}")


# -------------------------------------------------------------- report cards

@receiver(pre_save, sender="scheme.ReportCard", dispatch_uid="notif-card-pre")
def _card_before(sender, instance, **kwargs):
    _remember(sender, instance, ["published_at"])


@receiver(post_save, sender="scheme.ReportCard", dispatch_uid="notif-card-post")
def _card_after(sender, instance, created, **kwargs):
    if not instance.published_at or getattr(instance, "_before", {}).get("published_at"):
        return
    notify(instance.student_id, K.REPORT, f"Your report card for {instance.term} is ready",
           "Open it with a grown-up.", reverse("scheme:card", args=[instance.term_id, instance.student_id]),
           key=f"report-{instance.pk}")


# ------------------------------------------------------------ people joining

@receiver(post_save, sender="accounts.User", dispatch_uid="notif-joined")
def _joined(sender, instance, created, raw=False, **kwargs):
    if not created or raw or not instance.school_id:
        return
    who = name_of(instance)
    if instance.role == sender.Role.STUDENT:
        where = instance.school_class.display_name if instance.school_class_id else "your school"
        notify_many(teachers_of(instance), K.JOINED, f"{who} joined {where}", "A new pupil in your class.",
                    reverse("schools:class_dashboard"), key=f"joined-{instance.pk}")
        notify_many(admins_of(instance.school_id), K.JOINED, f"{who} joined as a student",
                    f"In {where}.", reverse("schools:classes"), key=f"joined-{instance.pk}")
    elif instance.role == sender.Role.TEACHER:
        notify_many(admins_of(instance.school_id), K.JOINED, f"{who} joined as a teacher",
                    "Give them their classes on the Classes page.", reverse("schools:classes"),
                    key=f"joined-{instance.pk}")


@receiver(post_save, sender="accounts.PasswordHelpRequest", dispatch_uid="notif-help")
def _help(sender, instance, created, **kwargs):
    if not created or not instance.school_id:
        return
    notify_many(admins_of(instance.school_id), K.HELP, f"{name_of(instance.user)} needs help with their password",
                "Set them a new one from the school dashboard.", reverse("schools:dashboard") + "#logins",
                key=f"help-{instance.pk}")
