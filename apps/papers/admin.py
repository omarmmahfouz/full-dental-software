from django.contrib import admin

from .models import PaperField, PaperFile, PaperPage, PaperReading, PaperSettings


class PageInline(admin.TabularInline):
    model = PaperPage
    extra = 0
    fields = ["number", "kind", "turned", "notes"]


@admin.register(PaperFile)
class PaperFileAdmin(admin.ModelAdmin):
    list_display = ["original_name", "branch", "status", "patient", "page_count", "created_at"]
    list_filter = ["status", "branch", "mode"]
    search_fields = ["original_name", "cover_number"]
    raw_id_fields = ["patient", "suggested", "document"]
    inlines = [PageInline]


@admin.register(PaperReading)
class PaperReadingAdmin(admin.ModelAdmin):
    list_display = ["page", "number", "status", "model", "batched", "input_tokens", "output_tokens", "done_at"]
    list_filter = ["status", "batched", "model"]
    raw_id_fields = ["page"]


@admin.register(PaperField)
class PaperFieldAdmin(admin.ModelAdmin):
    list_display = ["file", "name", "value", "certainty", "checked"]
    list_filter = ["certainty", "checked"]
    raw_id_fields = ["file", "page"]


admin.site.register(PaperSettings)
