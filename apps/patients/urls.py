from django.urls import path

from . import calllists, consults, views

app_name = "patients"

urlpatterns = [
    path("", views.PatientListView.as_view(), name="list"),
    path("new/", views.PatientCreateView.as_view(), name="create"),
    path("lookup/", views.patient_lookup, name="lookup"),
    path("phone-check/", views.phone_check, name="phone_check"),
    path("prefers/", views.patient_prefs, name="prefs"),
    path("<int:pk>/", views.patient_detail, name="detail"),
    path("<int:pk>/edit/", views.PatientUpdateView.as_view(), name="update"),
    path("<int:pk>/history/", views.medical_history, name="medical_history"),
    path("<int:pk>/records/", views.records_step, name="records"),
    path("<int:pk>/word/", views.patient_word, name="word"),
    path("<int:pk>/excel/", views.patient_excel, name="excel"),
    path("<int:pk>/documents/", views.document_upload, name="document_upload"),
    path("<int:pk>/documents/<int:doc_pk>/delete/", views.document_delete, name="document_delete"),
    path("<int:pk>/documents/<int:doc_pk>/rotate/", views.document_rotate, name="document_rotate"),
    path("<int:pk>/relations/", views.relation_add, name="relation_add"),
    path("<int:pk>/move/", views.patient_transfer, name="transfer"),
    path("<int:pk>/relations/<int:rel_pk>/delete/", views.relation_delete, name="relation_delete"),
    path("medical-follow-up/", consults.medical_followup, name="medical_followup"),
    path("medical-follow-up/calls/<int:pk>/", consults.recall_call, name="recall_call"),
    path("<int:pk>/consult/", consults.consult_create, name="consult_create"),
    path("<int:pk>/consult/medicines/", consults.consult_medications, name="consult_medications"),
    path("<int:pk>/consult/not-needed/", consults.consult_not_needed, name="consult_not_needed"),
    path("consults/<int:pk>/", consults.consult_detail, name="consult_detail"),
    path("consults/<int:pk>/edit/", consults.consult_update, name="consult_update"),
    path("consults/<int:pk>/answer/", consults.consult_answer, name="consult_answer"),
    path("calls/", views.LeadListView.as_view(), name="lead_list"),
    path("calls/new/", views.LeadCreateView.as_view(), name="lead_create"),
    path("calls/<int:pk>/", views.LeadDetailView.as_view(), name="lead_detail"),
    path("calls/<int:pk>/edit/", views.LeadUpdateView.as_view(), name="lead_update"),
    path("calls/<int:pk>/log/", views.lead_add_call, name="lead_add_call"),
    path("calls/<int:pk>/book/", views.lead_book, name="lead_book"),
    path("to-call/", calllists.calllist_list, name="calllist_list"),
    path("to-call/new/", calllists.calllist_create, name="calllist_create"),
    path("to-call/<int:pk>/", calllists.calllist_detail, name="calllist_detail"),
    path("to-call/answer/<int:pk>/", calllists.calllist_answer, name="calllist_answer"),
]
