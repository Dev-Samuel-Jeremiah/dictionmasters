"""hidden_tools: the tools on the Learn page this person may not open
(apps.accounts.access.can_use_tool), so menus can leave them out rather
than lead to a "not for your class" page. Only students are ever held
back, so only they pay for the one small lookup."""

from apps.accounts.access import can_use_tool, tool_levels


def hidden_tools(request):
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated or user.role != "student" or user.is_staff:
        return {"hidden_tools": ()}
    from .views import TOOLS

    kept = tool_levels()
    return {"hidden_tools": [t["url_name"] for t in TOOLS if not can_use_tool(user, t["url_name"], kept)]}
