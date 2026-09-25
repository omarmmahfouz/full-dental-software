from django.urls import path

from . import views

app_name = "patients"

urlpatterns = [
    path("", views.PatientListView.as_view(), name="list"),
    path("new/", views.PatientCreateView.as_view(), name="create"),
    path("<int:pk>/", views.patient_detail, name="detail"),
    path("<int:pk>/edit/", views.PatientUpdateView.as_view(), name="update"),
    path("<int:pk>/documents/", views.document_upload, name="document_upload"),
    path("<int:pk>/documents/<int:doc_pk>/delete/", views.document_delete, name="document_delete"),
    path("<int:pk>/relations/", views.relation_add, name="relation_add"),
    path("<int:pk>/relations/<int:rel_pk>/delete/", views.relation_delete, name="relation_delete"),
    path("calls/", views.LeadListView.as_view(), name="lead_list"),
    path("calls/new/", views.LeadCreateView.as_view(), name="lead_create"),
    path("calls/<int:pk>/", views.LeadDetailView.as_view(), name="lead_detail"),
    path("calls/<int:pk>/edit/", views.LeadUpdateView.as_view(), name="lead_update"),
    path("calls/<int:pk>/log/", views.lead_add_call, name="lead_add_call"),
]
