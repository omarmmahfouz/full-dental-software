from .models import PaperFile, ReaderSettings, SystemLists


def reader(request):
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return {}
    counts = dict.fromkeys(("review", "approved"), 0)
    for status in PaperFile.objects.filter(status__in=counts).values_list("status", flat=True):
        counts[status] += 1
    return {"lists": SystemLists.get(), "options": ReaderSettings.get(), "to_check": counts["review"],
            "ready_to_send": counts["approved"], "in_charge": user.is_staff}
