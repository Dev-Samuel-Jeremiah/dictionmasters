from django.urls import path

from . import views

app_name = "console"

urlpatterns = [
    path("search/", views.search, name="search"),
    path("jobs/word-audio/", views.generate_word_audio, name="generate_word_audio"),
    path("jobs/chart-audio/", views.generate_chart_audio, name="generate_chart_audio"),
    path("jobs/video-posters/", views.generate_video_posters, name="generate_video_posters"),
]
