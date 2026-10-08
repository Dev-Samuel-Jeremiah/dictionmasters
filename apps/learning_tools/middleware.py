"""
Keeps a whole tool for the levels staff chose (learning_tools.ToolLevels).

A student who opens a tool kept for other levels — by a bookmark, a link
from a friend, a QR code — gets a friendly page pointing back to Learn
instead of the tool. The rule itself is apps.accounts.access.can_use_tool;
this only finds which tool an address belongs to: the tool whose own
address is the longest start of it, so the Phonemic chart
(/book/phonemic-chart/) is told apart from the 44 Academy (/book/).
"""

from django.shortcuts import render
from django.urls import NoReverseMatch, reverse

from apps.accounts.access import can_use_tool, tool_levels

_prefixes = None


def _tool_prefixes():
    """[(address, url name)] for every tool, longest address first."""
    global _prefixes
    if _prefixes is None:
        from .views import TOOLS

        found = []
        for tool in TOOLS:
            try:
                found.append((reverse(tool["url_name"]), tool["url_name"]))
            except NoReverseMatch:
                continue
        _prefixes = sorted(found, key=lambda pair: len(pair[0]), reverse=True)
    return _prefixes


def tool_for_path(path):
    return next((name for prefix, name in _tool_prefixes() if path.startswith(prefix)), None)


class ToolLevelsMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        # Only students are ever held back, so nobody else pays for the lookup.
        if user is not None and user.is_authenticated and user.role == "student" and not user.is_staff:
            tool = tool_for_path(request.path)
            if tool and not can_use_tool(user, tool, tool_levels()):
                return render(request, "learning_tools/not_for_level.html", {"tool": tool}, status=403)
        return self.get_response(request)
