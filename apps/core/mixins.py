from functools import wraps

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.utils.translation import gettext_lazy as _

from .roles import has_role


class RoleRequiredMixin:
    """Restrict a class-based view to users holding one of ``allowed_roles``.
    (Login itself is enforced for every page by LoginRequiredMiddleware.)"""

    allowed_roles = ()

    def dispatch(self, request, *args, **kwargs):
        if not has_role(request.user, *self.allowed_roles):
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)


def role_required(*roles):
    def decorator(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            if not has_role(request.user, *roles):
                raise PermissionDenied
            return view(request, *args, **kwargs)

        return wrapper

    return decorator


class AuditMixin:
    """Stamp ``created_by`` on new records and show a success message."""

    success_message = _("Saved successfully.")

    def form_valid(self, form):
        if not form.instance.pk and hasattr(form.instance, "created_by_id"):
            form.instance.created_by = self.request.user
        response = super().form_valid(form)
        if self.success_message:
            messages.success(self.request, self.success_message)
        return response


class SearchMixin:
    """Keep the list's search box value (``q``) available to templates."""

    def get_search_query(self):
        return self.request.GET.get("q", "").strip()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["q"] = self.get_search_query()
        params = self.request.GET.copy()
        params.pop("page", None)
        context["query_string"] = params.urlencode()
        return context
