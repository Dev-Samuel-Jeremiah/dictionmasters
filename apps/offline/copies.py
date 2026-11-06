"""Telling a page kept for offline use from a learner opening it.

Some pages count as progress just by being opened: an EchoSpell card, a
Tricks or 44 Academy tab, a step of a Learning Modules day (and "pick up
where you left off" follows the last card opened). The app's lesson
download fetches every page with the learner's account, so without this it
would tick off lessons nobody had opened.

templates/pwa/sw.js sends one of two headers:

    X-DM-Offline-Copy: 1     a page fetched to keep on the device. Nothing
                             is recorded, and the "open every part of the
                             lesson first" rule is left to the visit, so an
                             activity is kept ready for when they get there.
    X-DM-Offline-Replay: 1   something the learner did offline (opened a
                             page, sent answers), sent now it's back online,
                             in the order they did it. Recorded as usual;
                             the "open every part first" rule wasn't checked
                             offline, so it isn't here either.

Neither opens anything locked: a lesson they haven't reached stays shut.
These are conveniences, not security: someone adding the header by hand
skips their own progress, nothing more.
"""

COPY = "X-DM-Offline-Copy"
REPLAY = "X-DM-Offline-Replay"


def is_copy(request):
    """A page being kept for offline use, not opened by the learner."""
    return request.headers.get(COPY) == "1"


def is_replay(request):
    return request.headers.get(REPLAY) == "1"


def opened(request):
    """Does opening this page count as the learner opening it?"""
    return not is_copy(request)


def parts_rule_applies(request):
    """Check "open every part of the lesson first"? Not for a copy being
    kept, nor for answers given offline."""
    return not (is_copy(request) or is_replay(request))


class ReplayedVisitMiddleware:
    """A page opened offline, opened again now it's back online so the visit
    counts (templates/pwa/sw.js): nobody looks at it, so nothing comes back
    but "done". Pupils on expensive data don't pay for the page twice."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        from django.http import HttpResponse

        response = self.get_response(request)
        if request.method == "GET" and is_replay(request) and response.status_code == 200:
            return HttpResponse(status=204)
        return response
