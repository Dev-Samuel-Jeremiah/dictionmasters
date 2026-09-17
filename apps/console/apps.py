from django.apps import AppConfig


class ConsoleConfig(AppConfig):
    """The Diction Masters admin console.

    It doesn't replace the Django admin: every add, edit, delete and
    upload still happens on the admin's own forms. It gives the admin a
    home page built for running the platform, puts the sidebar in feature
    order, and brands the whole admin.
    """

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.console"
    label = "console"
    verbose_name = "Admin console"

    def ready(self):
        from django.contrib import admin

        from .dashboard import console_context
        from .features import APP_ORDER

        site = admin.site
        site.site_header = "Diction Masters Admin"
        site.site_title = "Diction Masters Admin"
        site.index_title = "Admin console"

        original_index = site.index
        original_app_list = site.get_app_list

        def index(request, extra_context=None):
            return original_index(request, extra_context={**console_context(request), **(extra_context or {})})

        def get_app_list(request, app_label=None):
            app_list = original_app_list(request, app_label)
            rank = {label: position for position, label in enumerate(APP_ORDER)}
            return sorted(app_list, key=lambda app: (rank.get(app["app_label"], len(rank)), app["name"]))

        # Set on the instance before the admin's URLs are built, so the
        # admin home and sidebar use them.
        site.index = index
        site.get_app_list = get_app_list
