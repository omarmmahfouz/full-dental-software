from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_not_required
from django.urls import include, path, re_path
from django.utils.translation import gettext_lazy as _
from django.views.i18n import set_language

from apps.core.views import protected_media

admin.site.site_header = _("Dental group - system settings")
admin.site.site_title = _("Dental group")
admin.site.index_title = _("Settings and lists")

urlpatterns = [
    path("login/", auth_views.LoginView.as_view(), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("password/", auth_views.PasswordChangeView.as_view(), name="password_change"),
    path("password/done/", auth_views.PasswordChangeDoneView.as_view(), name="password_change_done"),
    path("i18n/setlang/", login_not_required(set_language), name="set_language"),
    path("admin/", admin.site.urls),
    re_path(r"^media/(?P<path>.+)$", protected_media, name="media"),
    path("", include("apps.core.urls")),
    path("patients/", include("apps.patients.urls")),
    path("schedule/", include("apps.scheduling.urls")),
    path("clinical/", include("apps.clinical.urls")),
    path("complaints/", include("apps.complaints.urls")),
    path("academy/", include("apps.academy.urls")),
    path("purchases/", include("apps.purchasing.urls")),
    path("reports/", include("apps.reports.urls")),
]
