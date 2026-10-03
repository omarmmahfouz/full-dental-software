"""Old paper files, the dental system's side (round 13): the lists for the Paper Reader, the cover sheets, and
importing the reader's packages (every value checked again with the system's forms). The reading itself is tested
in the reader program (``reader/reading/tests.py``)."""

import io
import json
import shutil
import tempfile
import zipfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.utils import translation

from apps.core.testing import PASSWORD, make_dentist, make_patient, make_user, setup_clinic
from apps.papers import importer
from apps.papers.demo import entry, make_package, scanned_pdf
from apps.papers.fields import BY_NAME, LISTS_KIND, NAMES
from apps.papers.models import ImportedFile, PaperImport
from apps.patients.models import MedicalCondition, Patient, PatientDocument

NID = "29001150101234"  # born 15/01/1990, Cairo, a man


def upload(data, name="paper-files-CIA.zip"):
    return SimpleUploadedFile(name, data, "application/zip")


class ImportTestCase(TestCase):
    @classmethod
    def setUpClass(cls):
        # A folder of its own for each class: the tests run in several processes at once.
        cls.media = tempfile.mkdtemp()
        cls.media_setting = override_settings(MEDIA_ROOT=cls.media)
        cls.media_setting.enable()
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        cls.media_setting.disable()
        shutil.rmtree(cls.media, ignore_errors=True)

    def setUp(self):
        self.branch = setup_clinic()
        self.owner = make_user("owner", "owner")
        self.secretary = make_user("sec", "secretary")
        self.dentist = make_dentist("mona", kind="fulltime", name="Dr. Mona Adel")
        self.client.login(username="sec", password=PASSWORD)

    def bring(self, *rows, place="CIA"):
        """Bring a package in (Look inside); returns the PaperImport."""
        response = self.client.post("/patients/papers/", {"package": upload(make_package(place, rows))})
        self.assertEqual(response.status_code, 302, getattr(response, "context", None) and
                         response.context["form"].errors)
        return PaperImport.objects.latest("pk")

    def new_file(self, **extra):
        diabetes = MedicalCondition.objects.filter(name_en="Diabetes").values_list("pk", flat=True).first()
        patient = {"full_name": "محمد أحمد علي حسن", "national_id": NID, "phone_primary": "01001234567",
                   "occupation": "Engineer", "registered_on": "03/04/2016", "gender": "M", "birth_date": "15/01/1990"}
        history = {"exam_date": "03/04/2016", "examined_by": str(self.dentist.pk), "bp_last_systolic": "130",
                   "bp_last_diastolic": "85", "conditions": str(diabetes), "allergy_penicillin": "yes",
                   "smoker": "yes", "cigarettes_per_day": "20", "hba1c": "7.8"}
        values = {"patient": patient, "history": history, "documents": {"file.pdf": scanned_pdf()}}
        values.update(extra)
        return entry("old file.pdf", **values)


class ImportTests(ImportTestCase):
    def test_a_new_patient_with_the_history_and_the_scanned_file(self):
        paper_import = self.bring(self.new_file())
        page = self.client.get(paper_import.get_absolute_url())
        self.assertTrue(page.context["rows"][0]["new"])
        self.assertEqual(Patient.objects.count(), 0)  # nothing is saved before Import
        response = self.client.post(paper_import.get_absolute_url())
        self.assertEqual(response.status_code, 302)
        patient = Patient.objects.get()
        self.assertEqual((patient.full_name, patient.national_id, patient.occupation, patient.branch),
                         ("محمد أحمد علي حسن", NID, "Engineer", self.branch))
        self.assertTrue(patient.file_number.startswith("CIA-"))
        self.assertEqual(patient.registered_on.isoformat(), "2016-04-03")
        history = patient.examinations.get()
        self.assertTrue(history.history_only)
        self.assertTrue(history.allergy_penicillin and history.smoker)
        self.assertEqual(str(history.hba1c), "7.8")
        self.assertEqual(history.examined_by, self.dentist)
        self.assertEqual(list(patient.medical_conditions.values_list("name_en", flat=True)), ["Diabetes"])
        document = patient.documents.get()
        self.assertEqual(document.kind, PatientDocument.Kind.OLD_FILE)
        self.assertTrue(document.notes)
        paper_import.refresh_from_db()
        self.assertEqual(paper_import.status, PaperImport.Status.DONE)
        self.assertFalse(paper_import.package)  # the ZIP is not kept: the documents are in the patient's file
        result = paper_import.results.get()
        self.assertEqual((result.status, result.patient, result.new_patient),
                         (ImportedFile.Status.IMPORTED, patient, True))
        self.assertContains(self.client.get(paper_import.get_absolute_url()), patient.file_number)
        # What happened is kept as codes: each person reads it in their own language.
        self.assertEqual([code for code, _n in result.notes], ["new_file", "history", "documents"])
        with translation.override("en"):
            self.assertIn("A new file was opened.", result.what_happened)
        with translation.override("ar"):
            self.assertNotIn("A new file was opened.", result.what_happened)

    def test_a_file_is_imported_once_only(self):
        row = self.new_file()
        first = self.bring(row)
        self.client.post(first.get_absolute_url())
        again = self.bring(row)
        page = self.client.get(again.get_absolute_url())
        self.assertTrue(page.context["rows"][0]["skip"])
        self.client.post(again.get_absolute_url())
        self.assertEqual(Patient.objects.count(), 1)
        self.assertEqual(again.results.get().status, ImportedFile.Status.SKIPPED)
        self.assertEqual(PatientDocument.objects.count(), 1)

    def test_into_a_registered_patient_only_empty_fields_are_filled_and_a_change_waits_for_approval(self):
        from apps.core.models import ChangeRequest

        patient = make_patient(self.branch, name="محمد أحمد علي حسن", nid=NID, phone="01009998887", occupation="")
        row = entry("old file.pdf", target="existing", file_number=patient.file_number.lower(),
                    patient={"occupation": "Engineer", "phone_primary": "01001234567", "full_name": "اسم آخر تماما"},
                    replace=["phone_primary"], documents={"file.pdf": scanned_pdf()})
        paper_import = self.bring(row)
        self.client.post(paper_import.get_absolute_url())
        patient.refresh_from_db()
        self.assertEqual(patient.occupation, "Engineer")  # empty: filled
        self.assertIn(["filled", 1], paper_import.results.get().notes)
        self.assertEqual(patient.full_name, "محمد أحمد علي حسن")  # not empty and not ticked: kept
        self.assertEqual(patient.phone_primary, "01009998887")  # replaced only after the head approves
        change = ChangeRequest.objects.get()
        self.assertEqual(change.changes[0]["field"], "phone_primary")
        result = paper_import.results.get()
        self.assertEqual((result.patient, result.new_patient, result.change), (patient, False, change))
        self.assertEqual(Patient.objects.count(), 1)

    def test_the_head_replaces_directly(self):
        patient = make_patient(self.branch, nid=NID, phone="01009998887")
        self.client.login(username="owner", password=PASSWORD)
        row = entry("old.pdf", target="existing", file_number=patient.file_number,
                    patient={"phone_primary": "01001234567"}, replace=["phone_primary"])
        self.client.post(self.bring(row).get_absolute_url())
        patient.refresh_from_db()
        self.assertEqual(patient.phone_primary, "01001234567")

    def test_the_same_national_id_goes_into_the_registered_file(self):
        patient = make_patient(self.branch, name="محمد أحمد علي حسن", nid=NID, phone="01009998887")
        paper_import = self.bring(self.new_file())
        page = self.client.get(paper_import.get_absolute_url())
        self.assertEqual(page.context["rows"][0]["patient"], patient)
        self.client.post(paper_import.get_absolute_url())
        self.assertEqual(Patient.objects.count(), 1)
        self.assertEqual(patient.documents.count(), 1)

    def test_pages_only(self):
        patient = make_patient(self.branch)
        row = entry("old.pdf", target="existing", file_number=patient.file_number, pages_only=True,
                    patient={"occupation": "Engineer"}, documents={"file.pdf": scanned_pdf()})
        self.client.post(self.bring(row).get_absolute_url())
        patient.refresh_from_db()
        self.assertEqual(patient.occupation, "")  # pages only: no value is taken
        self.assertEqual(patient.documents.get().kind, PatientDocument.Kind.OLD_FILE)
        self.assertFalse(patient.examinations.exists())

    def test_a_wrong_value_stops_that_file_only(self):
        bad = entry("bad.pdf", patient={"full_name": "Mohamed", "national_id": "123", "phone_primary": "0100"},
                    documents={"file.pdf": scanned_pdf()})
        paper_import = self.bring(bad, self.new_file())
        self.client.post(paper_import.get_absolute_url())
        results = list(paper_import.results.order_by("pk"))
        self.assertEqual([result.status for result in results], ["failed", "imported"])
        self.assertTrue(results[0].message)
        self.assertEqual(Patient.objects.count(), 1)
        self.assertEqual(PatientDocument.objects.count(), 1)  # nothing of the bad file was kept
        # The failed file can be sent again later.
        self.assertFalse(ImportedFile.objects.filter(token=results[0].token, status="imported").exists())

    def test_a_document_that_is_not_what_it_says_is_refused(self):
        row = self.new_file(documents={"file.pdf": b"MZ this is a program"})
        paper_import = self.bring(row)
        self.client.post(paper_import.get_absolute_url())
        self.assertEqual(paper_import.results.get().status, "failed")
        self.assertEqual(Patient.objects.count(), 0)

    def test_an_unknown_file_number(self):
        row = entry("old.pdf", target="existing", file_number="CIA-99999", patient={"occupation": "x"})
        paper_import = self.bring(row)
        self.assertIn("CIA-99999", self.client.get(paper_import.get_absolute_url()).context["rows"][0]["problem"])

    def test_the_package_must_be_the_readers_and_for_this_place(self):
        response = self.client.post("/patients/papers/", {"package": upload(b"PK\x03\x04 not really a zip")})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["form"].errors)
        response = self.client.post("/patients/papers/", {"package": upload(b"%PDF-1.4", name="x.pdf")})
        self.assertTrue(response.context["form"].errors)
        response = self.client.post("/patients/papers/", {"package": upload(make_package("CIC", [self.new_file()]))})
        self.assertEqual(response.status_code, 200)
        self.assertIn("CIC", str(response.context["form"].errors))
        self.assertEqual(PaperImport.objects.count(), 0)

    def test_paths_inside_the_package_are_checked(self):
        row, files = self.new_file()
        row["documents"]["file"] = "../../settings.py"
        with self.assertRaises(importer.PackageProblem):
            importer.read_manifest(io.BytesIO(make_package("CIA", [(row, files)])))
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w") as package:
            package.writestr("manifest.json", json.dumps({"kind": "cia-paper-reader-package", "version": 99,
                                                          "files": []}))
        with self.assertRaises(importer.PackageProblem):
            importer.read_manifest(io.BytesIO(output.getvalue()))

    def test_do_not_import(self):
        paper_import = self.bring(self.new_file())
        self.client.post(f"/patients/papers/imports/{paper_import.pk}/cancel/")
        self.assertFalse(PaperImport.objects.exists())
        self.assertEqual(Patient.objects.count(), 0)


class ListsAndAccessTests(ImportTestCase):
    def test_the_lists_for_the_reader(self):
        make_patient(self.branch, name="سعاد محمود عبد الله", nid="28512120101245", phone="01112223334",
                     occupation="Teacher")
        from apps.core.models import Branch

        make_patient(Branch.objects.get(code="CIC"), name="مريض في مكان آخر", nid="28512120101246")
        response = self.client.get("/patients/papers/lists/")
        self.assertIn("attachment", response["Content-Disposition"])
        data = json.loads(response.content)
        self.assertEqual((data["kind"], data["place"]["code"]), (LISTS_KIND, "CIA"))
        self.assertEqual([row["name"] for row in data["fields"]], NAMES)
        fields = {row["name"]: row for row in data["fields"]}
        self.assertTrue(fields["full_name"]["required"])
        self.assertEqual(fields["gender"]["choices"][0][0], "M")
        self.assertIn(["21", "Giza", "الجيزة"], fields["governorate"]["choices"])
        self.assertIn([str(self.dentist.pk), "Dr. Mona Adel", "Dr. Mona Adel"], fields["examined_by"]["choices"])
        self.assertEqual(fields["hba1c"]["range"], [3, 20])
        self.assertTrue(fields["conditions"]["choices"])
        self.assertTrue(fields["full_name"]["label_ar"])
        # Only the patients of this place.
        self.assertEqual([row["national_id"] for row in data["patients"]], ["28512120101245"])
        self.assertEqual(data["patients"][0]["values"]["occupation"], "Teacher")
        self.assertEqual(set(BY_NAME), set(fields))

    def test_who_opens_the_old_paper_files(self):
        from apps.core.models import Branch, UserProfile

        paper_import = self.bring(self.new_file())
        make_user("doc", "dentist")
        self.client.login(username="doc", password=PASSWORD)
        for url in ("/patients/papers/", "/patients/papers/lists/", paper_import.get_absolute_url()):
            self.assertEqual(self.client.get(url).status_code, 403, url)
        # The reception of another place does not open this place's package.
        other = make_user("cicsec", "secretary")
        UserProfile.objects.update_or_create(user=other, defaults={"branch": Branch.objects.get(code="CIC")})
        self.client.login(username="cicsec", password=PASSWORD)
        self.assertEqual(self.client.get(paper_import.get_absolute_url()).status_code, 403)
        self.assertEqual(self.client.post(paper_import.get_absolute_url()).status_code, 403)
        self.assertEqual(Patient.objects.count(), 0)
        self.client.login(username="sec", password=PASSWORD)
        self.assertContains(self.client.get("/patients/papers/"), paper_import.name)

    def test_cover_sheets(self):
        patient = make_patient(self.branch)
        page = self.client.get(f"/patients/papers/covers/?patient={patient.file_number}&blank=2")
        self.assertContains(page, patient.file_number)
        self.assertEqual(page.content.decode().count('class="cover-sheet"'), 3)

    def test_the_demo_packages(self):
        from apps.papers.demo import load_papers

        patients = [make_patient(self.branch, nid=f"2900115010{n:04d}", phone=f"0100123450{n}", occupation="")
                    for n in range(3)]
        load_papers(patients, self.secretary)
        done, waiting = PaperImport.objects.order_by("created_at")
        self.assertEqual(done.status, "done")
        self.assertEqual(waiting.status, "checked")
        self.assertTrue(Patient.objects.filter(full_name="سامية عبد الرحمن محمود").exists())
        self.assertEqual(patients[2].documents.count(), 1)
        self.client.post(waiting.get_absolute_url())
        self.assertEqual(Patient.objects.get(pk=patients[1].pk).occupation, "مدرس")
