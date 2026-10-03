from django.contrib import admin

from .models import ImportedFile, PaperImport


class ResultInline(admin.TabularInline):
    model = ImportedFile
    extra = 0
    fields = ["name", "status", "patient", "new_patient", "message"]
    raw_id_fields = ["patient"]


@admin.register(PaperImport)
class PaperImportAdmin(admin.ModelAdmin):
    list_display = ["name", "branch", "status", "created_at", "imported_at"]
    list_filter = ["status", "branch"]
    inlines = [ResultInline]
