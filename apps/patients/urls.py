from django.urls import path

from . import calllists, views

app_name = "patients"

urlpatterns = [
    path("", views.PatientListView.as_view(), name="list"),
    path("new/", views.PatientCreateView.as_view(), name="create"),
    path("lookup/", views.patient_lookup, name="lookup"),
    path("phone-check/", views.phone_check, name="phone_check"),
    path("<int:pk>/", views.patient_detail, name="detail"),
    path("<int:pk>/edit/", views.PatientUpdateView.as_view(), name="update"),
    path("<int:pk>/documents/", views.document_upload, name="document_upload"),
    path("<int:pk>/documents/<int:doc_pk>/delete/", views.document_delete, name="document_delete"),
    path("<int:pk>/documents/<int:doc_pk>/rotate/", views.document_rotate, name="document_rotate"),
    path("<int:pk>/relations/", views.relation_add, name="relation_add"),
    path("<int:pk>/relations/<int:rel_pk>/delete/", views.relation_delete, name="relation_delete"),
    path("calls/", views.LeadListView.as_view(), name="lead_list"),
    path("calls/new/", views.LeadCreateView.as_view(), name="lead_create"),
    path("calls/<int:pk>/", views.LeadDetailView.as_view(), name="lead_detail"),
    path("calls/<int:pk>/edit/", views.LeadUpdateView.as_view(), name="lead_update"),
    path("calls/<int:pk>/log/", views.lead_add_call, name="lead_add_call"),
    path("to-call/", calllists.calllist_list, name="calllist_list"),
    path("to-call/new/", calllists.calllist_create, name="calllist_create"),
    path("to-call/<int:pk>/", calllists.calllist_detail, name="calllist_detail"),
    path("to-call/answer/<int:pk>/", calllists.calllist_answer, name="calllist_answer"),
]
