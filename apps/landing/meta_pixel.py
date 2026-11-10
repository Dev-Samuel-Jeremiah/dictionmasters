"""Meta (Facebook) Pixel: which ads bring parents, teachers and schools here.

Diction Masters is used by children, and Meta's business terms don't allow
sending it data about children under 13; Nigeria's data protection law and
the GDPR expect consent before tracking. So the pixel is kept to the doors
adults come in by, and only once the visitor accepts:

  * Pages: the home page, the welcome tour and the sign-up pages for a
    school, a school team and an individual (adult) learner (PIXEL_PAGES),
    for visitors not signed in. Never a pupil's sign-up or "join with a
    code", never a lesson, the control room or any signed-in page, and
    never inside the Android, iPhone or desktop apps.
  * One event after: "CompleteRegistration", on the first page after an
    adult signs up (mark_signup), with Meta's automatic collection of page
    details switched off. Nothing else from a signed-in page.
  * Consent: a banner on those pages (static/js/meta_pixel.js); nothing
    loads from Meta until "Accept". The choice is kept in the browser and
    can be changed on the privacy page.

META_PIXEL_ID (Django settings, from the environment) switches it on; with
none set, nothing is sent anywhere.
"""

from django.conf import settings

PIXEL_PAGES = {
    "landing:home", "landing:tour",
    "accounts:register_choice", "accounts:register_school",
    "accounts:register_school_team", "accounts:register_individual",
}
# On their way to a pupil's sign-up, visitors see the welcome tour first
# (?next=...): probably a child, so no pixel there either.
PUPIL_DOORS = ("/accounts/register/student/", "/accounts/join/")
SIGNUP_KEY = "dm_meta_signup"
NEVER = ("/billing/", "/manage/", "/admin/", "/console/")


def mark_signup(request):
    """An adult (school, school team or individual learner) has just signed
    up: the next page tells Meta, once, if they accepted."""
    if getattr(settings, "META_PIXEL_ID", ""):
        request.session[SIGNUP_KEY] = True


def context(request):
    """`meta_pixel` for templates/includes/meta_pixel.html: {id, event,
    banner}, or nothing on a page that mustn't have it."""
    pixel = getattr(settings, "META_PIXEL_ID", "")
    if not pixel:
        return {}
    from .native_app import platform_of

    if platform_of(request):
        return {}
    match = getattr(request, "resolver_match", None)
    page = match.view_name if match else ""
    user = getattr(request, "user", None)
    signed_in = bool(user and user.is_authenticated)
    if page in PIXEL_PAGES and not signed_in:
        if request.GET.get("next", "").startswith(PUPIL_DOORS):
            return {}
        return {"meta_pixel": {"id": pixel, "event": "", "banner": True}}
    session = getattr(request, "session", None)
    if (signed_in and session is not None and session.get(SIGNUP_KEY)
            and request.method == "GET" and not request.path.startswith(NEVER)):
        del session[SIGNUP_KEY]
        return {"meta_pixel": {"id": pixel, "event": "CompleteRegistration", "banner": False}}
    return {}
