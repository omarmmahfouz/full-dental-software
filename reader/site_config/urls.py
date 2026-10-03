from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_not_required
from django.urls import include, path, re_path
from django.views.i18n import set_language

from reading.views import LoginView, protected_media, setup_owner

urlpatterns = [
    path("login/", LoginView.as_view(), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("setup/", setup_owner, name="setup_owner"),
    path("i18n/setlang/", login_not_required(set_language), name="set_language"),
    re_path(r"^media/(?P<path>.+)$", protected_media, name="media"),
    path("", include("reading.urls")),
]
