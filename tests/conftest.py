import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import create_app, initialize_database
from models import db, Section, User
from werkzeug.security import generate_password_hash

TEST_HASH = generate_password_hash("TestPassword123")


@pytest.fixture
def app(tmp_path):
    app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test-secret-only",
            "SQLALCHEMY_DATABASE_URI": "sqlite:///" + str(tmp_path / "test.db"),
            "UPLOAD_FOLDER": str(tmp_path / "uploads"),
            "WTF_CSRF_ENABLED": False,
            "PUBLIC_URL": "https://portal.example.fr",
            "SMTP_HOST": "",
            "SMTP_FROM": "",
        }
    )
    with app.app_context():
        initialize_database()
        sec = Section.query.first()
        other = Section(nom="Autre section")
        db.session.add(other)
        db.session.flush()
        for username, role, section, level in [
            ("admin", "admin", None, "N/A"),
            ("teacher", "formateur", sec.id, "N/A"),
            ("teacher2", "formateur", sec.id, "N/A"),
            ("pupil", "jsp", sec.id, "JSP 1"),
            ("pupil2", "jsp", sec.id, "JSP 2"),
            ("outsider", "formateur", other.id, "N/A"),
            ("outsidepupil", "jsp", other.id, "JSP 1"),
        ]:
            db.session.add(
                User(
                    username=username,
                    role=role,
                    section_id=section,
                    level=level,
                    nom="Test",
                    prenom=username,
                    email=username + "@example.fr",
                    first_login=False,
                    password_hash=TEST_HASH,
                )
            )
        db.session.commit()
    yield app
    with app.app_context():
        db.session.remove()
        db.engine.dispose()


@pytest.fixture
def client(app):
    return app.test_client()


def login(client, username="teacher", section="1"):
    return client.post(
        "/login",
        data={
            "username": username,
            "password": "TestPassword123",
            "section_id": section,
        },
    )
