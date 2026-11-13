"""
Screenshots and screen recording in the apps: blocked, or allowed for this
person.

The Android app and the computer app start every window blocked (black in
screenshots, recordings and screen sharing). Each page then says whether
the person signed in may capture it: <html data-capture="allow|block">
(templates/base.html), which static/js/screen_capture.js hands to the app.
Only staff and admin accounts are ever allowed, and only while the control
room's switch is on (ScreenProtection). Anyone else, or anyone signed out,
is blocked.

Being straight about the limit: an app can only ask the phone or computer
not to show its window in captures. iPhones and web browsers don't allow
even that, and a camera pointed at the screen still works.
"""

from .models import ScreenProtection


def may_capture(user):
    """May this person take screenshots and record the screen in the apps?"""
    if not (user and user.is_authenticated and (user.is_staff or user.is_superuser)):
        return False
    return ScreenProtection.load().staff_may_capture
