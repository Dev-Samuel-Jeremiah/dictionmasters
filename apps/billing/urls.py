from django.urls import path

from . import views

app_name = "billing"

urlpatterns = [
    path("", views.account, name="account"),
    path("plans/", views.pricing, name="pricing"),
    path("trial/", views.trial, name="trial"),
    path("student-prices/", views.student_prices, name="student_prices"),
    path("checkout/<slug:slug>/", views.checkout, name="checkout"),
    path("callback/", views.callback, name="callback"),
    path("webhook/paystack/", views.webhook, name="webhook"),
    path("receipt/<str:reference>/", views.receipt, name="receipt"),
]
