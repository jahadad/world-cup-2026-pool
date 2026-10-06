from django.contrib.auth import views as auth_views
from django.urls import path

from . import views

urlpatterns = [
    path("", views.fixture, name="fixture"),
    path("match/<int:number>/", views.match_detail, name="match_detail"),
    path("save/<int:number>/", views.save_prediction, name="save_prediction"),
    path("ranking/", views.leaderboard, name="leaderboard"),
    path("groups/", views.groups, name="groups"),
    path("leagues/", views.tournaments, name="tournaments"),
    path("leagues/create/", views.create_tournament, name="create_tournament"),
    path("leagues/join/", views.join_tournament_form, name="join_tournament_form"),
    path("leagues/<str:code>/", views.tournament_detail, name="tournament_detail"),
    path("t/<str:code>/", views.join_tournament, name="join_tournament"),
    path("signup/", views.register, name="register"),
    path("login/", views.ThrottledLoginView.as_view(), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
]
