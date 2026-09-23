from django.contrib import admin

from .models import RadioEpisode, RadioProgram


class RadioEpisodeInline(admin.TabularInline):
    model = RadioEpisode
    extra = 0
    fields = ["order", "title", "audio_file", "audio_url", "is_published"]
    show_change_link = True


@admin.register(RadioProgram)
class RadioProgramAdmin(admin.ModelAdmin):
    list_display = ["title", "presenter", "order", "is_published", "episode_count"]
    list_filter = ["is_published"]
    search_fields = ["title", "tagline", "presenter", "description"]
    prepopulated_fields = {"slug": ("title",)}
    inlines = [RadioEpisodeInline]

    def episode_count(self, obj):
        return obj.episodes.count()
    episode_count.short_description = "Episodes"


@admin.register(RadioEpisode)
class RadioEpisodeAdmin(admin.ModelAdmin):
    list_display = ["title", "program", "order", "is_published", "updated_at"]
    list_filter = ["program", "is_published"]
    search_fields = ["title", "description", "program__title"]
