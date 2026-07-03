import base64
import uuid
import unittest

from db.crypto import (
    decrypt_json,
    encrypt_json,
    require_session_kek,
    reset_session_kek,
    set_session_kek,
    unwrap_data_key,
    wrap_data_key,
    zero_bytes,
)
from db.models import ChatSession, DiagnosisSession, IntakeSession, User
from db.repositories import DiagnosisRepo, IntakeRepo, SessionRepo, _normalize_unique_identifier
from db.schemas import IntakeProfile, Symptom


SESSION_KEY = base64.b64encode(b"s" * 32).decode("ascii")


class FakeAsyncDB:
    def __init__(self):
        self.objects = {}

    def add(self, obj):
        self.objects[(type(obj), obj.id)] = obj

    async def flush(self):
        pass

    async def get(self, model, ident):
        if isinstance(ident, str):
            ident = uuid.UUID(ident)
        return self.objects.get((model, ident))


def sample_profile():
    symptom = Symptom(
        name="Headache",
        severity="moderate",
        duration="2 days",
        location="temple",
        character="throbbing",
        aggravating_factors=["light"],
        alleviating_factors=["rest"],
        onset="gradual",
        radiation="none",
    )
    return IntakeProfile(
        name=None,
        age=35,
        chief_complaint="Headache",
        symptoms=[symptom],
        pmh="none",
        medications=[],
        lifestyle={},
        allergies=[],
        family_history="none",
        red_flags=["fever"],
        medical_summary="## Summary",
    )


class DbTests(unittest.IsolatedAsyncioTestCase):
    async def test_crypto_roundtrip_and_wrong_purpose_rejection(self):
        token = set_session_kek(SESSION_KEY)
        user_id = uuid.uuid4()
        data_key = bytearray(b"d" * 32)
        try:
            wrapped = wrap_data_key(data_key, user_id)
            self.assertEqual(unwrap_data_key(wrapped, user_id), data_key)

            encrypted = encrypt_json(data_key, user_id, "profile", {"age": 35})
            self.assertEqual(decrypt_json(data_key, user_id, "profile", encrypted), {"age": 35})
            with self.assertRaises(Exception):
                decrypt_json(data_key, user_id, "other-purpose", encrypted)
        finally:
            reset_session_kek(token)

        with self.assertRaises(ValueError):
            require_session_kek()

    async def test_zero_bytes_overwrites_bytearray(self):
        value = bytearray(b"secret")
        zero_bytes(value)
        self.assertEqual(value, b"\x00" * 6)

    async def test_model_defaults_and_to_dict(self):
        user = User(ssh_key="ssh-ed25519 test")
        intake = IntakeSession(user_id=user.id)
        chat = ChatSession(user_id=user.id, intake_session=intake, intake_session_id=intake.id)

        self.assertEqual(intake.status, "in_progress")
        self.assertEqual(chat.user_id, user.id)
        self.assertIsNone(user.email)
        self.assertEqual(user.to_dict()["ssh_key"], "ssh-ed25519 test")

    async def test_intake_repo_creates_completes_reads_and_enforces_user(self):
        token = set_session_kek(SESSION_KEY)
        try:
            db = FakeAsyncDB()
            user_id = uuid.uuid4()
            other_user_id = uuid.uuid4()
            db.add(User(id=user_id, ssh_key="user-key"))
            db.add(User(id=other_user_id, ssh_key="other-key"))

            repo = IntakeRepo(str(user_id))
            session = await repo.create_session(db)

            before = await repo.get_session(db, session.id)
            self.assertEqual(before.status, "in_progress")

            result = await repo.complete_session(db, session.id, sample_profile(), "thread-1")
            self.assertEqual(result, "OK")
            self.assertNotIn("Headache", session.encrypted_payload)

            after = await repo.get_session(db, session.id)
            self.assertEqual(after.chief_complaint, "Headache")
            self.assertEqual(after.symptoms[0]["name"], "Headache")
            self.assertEqual(after.red_flags, ["fever"])
            self.assertEqual(after.thread_id, "thread-1")

            other_repo = IntakeRepo(str(other_user_id))
            self.assertIsNone(await other_repo.get_session(db, session.id))
            self.assertEqual(
                await other_repo.complete_session(db, session.id, sample_profile(), "thread-2"),
                "Error: Unauthorized",
            )
        finally:
            reset_session_kek(token)

    async def test_diagnosis_repo_encrypts_and_reads_report(self):
        token = set_session_kek(SESSION_KEY)
        try:
            db = FakeAsyncDB()
            user_id = uuid.uuid4()
            db.add(User(id=user_id, ssh_key="user-key"))
            intake = IntakeSession(user_id=user_id)
            db.add(intake)

            saved = await DiagnosisRepo(str(user_id)).create_diagnosis_session(
                db,
                intake.id,
                {"primary_diagnosis": "Migraine"},
            )
            raw = db.objects[(DiagnosisSession, saved.id)]
            self.assertNotIn("Migraine", raw.encrypted_payload)

            read = await DiagnosisRepo(str(user_id)).get_diagnosis_session(db, saved.id)
            self.assertEqual(read.report["primary_diagnosis"], "Migraine")
            self.assertEqual(read.intake_session_id, intake.id)
        finally:
            reset_session_kek(token)

    async def test_session_repo_create_get_and_link(self):
        db = FakeAsyncDB()
        user_id = uuid.uuid4()
        other_user_id = uuid.uuid4()
        repo = SessionRepo()

        session = await repo.create_session(db, user_id)
        intake = IntakeSession(user_id=user_id)
        db.add(intake)

        self.assertEqual(await repo.get_session(db, user_id, session.id), session)
        self.assertIsNone(await repo.get_session(db, other_user_id, session.id))

        linked = await repo.link_session(db, user_id, session.id, intake)
        self.assertEqual(linked.intake_session_id, intake.id)

    async def test_unique_identifier_normalization(self):
        self.assertEqual(_normalize_unique_identifier("  DOI:ABC  "), "doi:abc")
        self.assertIsNone(_normalize_unique_identifier("   "))
        self.assertIsNone(_normalize_unique_identifier(None))


if __name__ == "__main__":
    unittest.main()
