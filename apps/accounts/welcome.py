"""
The welcome email someone gets when they sign up, written for who they are:

    a school admin       their school code and how to bring teachers and students in
    a teacher            their school, their level(s) and the teacher tools
    a student            where to start and how to keep a streak
    an individual        their free trial and where to start

Only people with an email of their own get one (students made by their
school with just a username have no inbox to send to). It is sent after the
sign-up has been saved, in the background, so a slow mail server never
holds up the page; a failure is logged, never shown.
"""

import logging
import threading

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.db import transaction
from django.template.loader import render_to_string
from django.urls import reverse

logger = logging.getLogger("apps.accounts.welcome")


def _site(request):
    return (getattr(settings, "SITE_URL", "") or (request.build_absolute_uri("/") if request else "")).rstrip("/")


def _context(request, user):
    site = _site(request)
    role = user.role
    school = user.school
    context = {
        "user": user,
        "site_url": site,
        "login_url": site + reverse("accounts:login"),
        "login_name": user.login_name,
        "school": school,
        "role": role,
        "levels": user.level_display,
        "forgot_url": site + reverse("accounts:password_forgot"),
    }
    if role == "school_admin":
        context.update(
            headline=f"Welcome, {school.name if school else 'your school'}!",
            intro="Your school is set up on Diction Masters. Here’s how to bring everyone in.",
            dashboard_url=site + reverse("schools:dashboard"),
            steps=[
                ("Share your school code", f"Teachers and students sign up with the code {school.code if school else ''} and choose their level. Your plan covers everyone."),
                ("Watch your school grow", "Your dashboard shows every teacher and student, their levels, and their login details if they forget them."),
                ("Promote at the end of a session", "Move whole classes up a level in a few taps, with a preview first and an undo."),
            ],
            cta="Open my school dashboard",
        )
    elif role == "teacher":
        context.update(
            headline=f"Welcome to {school.name if school else 'Diction Masters'}, {user.first_name}!",
            intro="You’re all set to teach with Diction Masters" + (f" in {user.level_display}." if user.level_display else "."),
            dashboard_url=site + reverse("accounts:dashboard"),
            steps=[
                ("Lesson Notes to Audio", "Upload, paste or write a lesson note and hear it in a natural British voice, then practise its key words."),
                ("The 44 Academy", "A full lesson for every sound of English: perfect for modelling pronunciation in class."),
                ("Diction Library", "Books, stories and audio for your pupils, read aloud with every word highlighted."),
            ],
            cta="Go to my dashboard",
        )
    elif role == "student":
        context.update(
            headline=f"Welcome, {user.first_name}!",
            intro="Your Diction Masters account is ready" + (f" for {user.level_display}." if user.level_display else "."),
            dashboard_url=site + reverse("accounts:dashboard"),
            steps=[
                ("Start with EchoSpell", "Listen, spell and say new words, one group at a time."),
                ("Practise a little every day", "A few minutes daily keeps your streak going and your pronunciation growing."),
                ("Read with Yela", "Read aloud to the AI tutor; it helps with any word you find hard."),
            ],
            cta="Start learning",
        )
    else:
        context.update(
            headline=f"Welcome to Diction Masters, {user.first_name}!",
            intro="Your private British English tutor is ready whenever you are.",
            dashboard_url=site + reverse("accounts:dashboard"),
            steps=[
                ("Start your free trial", "Every course and tool is open to you during your trial."),
                ("The 44 Academy", "Master every sound of English, one clear lesson at a time."),
                ("Practise daily", "A few minutes a day builds a streak and real, lasting progress."),
            ],
            cta="Start learning",
        )
    return context


def _build(request, user):
    context = _context(request, user)
    subject = (f"Welcome to Diction Masters, {user.school.name}" if user.role == "school_admin" and user.school
               else "Welcome to Diction Masters")
    text = render_to_string("accounts/email/welcome.txt", context)
    html = render_to_string("accounts/email/welcome.html", context)
    message = EmailMultiAlternatives(subject, text, settings.DEFAULT_FROM_EMAIL, [user.email])
    message.attach_alternative(html, "text/html")
    return message


def _deliver(message, user_pk):
    try:
        message.send()
        logger.info("Welcome email sent to user %s", user_pk)
    except Exception:
        logger.exception("Welcome email to user %s couldn't be sent", user_pk)


def send_welcome(request, user):
    """Welcome a new account by email, once the sign-up is saved. Returns
    False when there's no inbox to send to."""
    if user is None or not user.has_real_email:
        return False
    message = _build(request, user)                 # built now, while the request is here
    if getattr(settings, "WELCOME_EMAIL_SYNC", False) or getattr(settings, "TESTING", False):
        transaction.on_commit(lambda: _deliver(message, user.pk))
    else:
        transaction.on_commit(lambda: threading.Thread(target=_deliver, args=(message, user.pk), daemon=True).start())
    return True
