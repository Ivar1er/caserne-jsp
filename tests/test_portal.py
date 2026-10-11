import io
import re
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch
import pytest
from itsdangerous import URLSafeTimedSerializer
from werkzeug.security import check_password_hash
from app import initialize_database, create_app
from models import (
    db,
    Section,
    User,
    Event,
    EventResponse,
    Grade,
    Course,
    Evaluation,
    JspDocument,
    Alerte,
    Progress,
    Equipment,
    Transaction,
)
from conftest import login


def create_event(client, target="JSP 1", kind="seance"):
    response = client.post(
        "/formateur/create-event",
        data={
            "title": "Test exercice",
            "date_time": "2026-11-12T14:00",
            "end_time": "2026-11-12T17:00",
            "target_level": target,
            "event_type": kind,
        },
    )
    assert response.status_code == 302
    return 1


def upload(client, url="/formateur/upload-course", filename="cours.pdf", **extra):
    return client.post(
        url,
        data={
            "title": "Document test",
            "file": (io.BytesIO(b"%PDF-1.4\n test"), filename),
            **extra,
        },
        content_type="multipart/form-data",
    )


@pytest.mark.parametrize(
    "username,path",
    [("admin", "/admin/sections"), ("teacher", "/formateur"), ("pupil", "/jsp")],
)
def test_dashboards(app, client, username, path):
    assert login(client, username).status_code == 302
    assert client.get(path).status_code == 200
    assert b"csrf_token" in client.get(path).data


@pytest.mark.parametrize(
    "path", ["/formateur", "/jsp", "/profile", "/admin/sections", "/documents/course/1"]
)
def test_requires_login(client, path):
    assert client.get(path).status_code == 302


@pytest.mark.parametrize(
    "username,password,sec",
    [("pupil", "TestPassword123", "2"), ("unknown", "bad", "1"), ("pupil", "", "1")],
)
def test_invalid_login(client, username, password, sec):
    response = client.post(
        "/login", data={"username": username, "password": password, "section_id": sec}
    )
    assert response.status_code == 200 and "incorrect" in response.text
    assert client.get("/jsp").status_code == 302


def test_case_insensitive_login(client):
    assert (
        login(client, "TEACHER").status_code == 302
        and client.get("/formateur").status_code == 200
    )


def test_first_login(app, client):
    with app.app_context():
        u = User.query.filter_by(username="pupil").one()
        u.first_login = True
        db.session.commit()
    login(client, "pupil")
    for path in ["/jsp", "/profile", "/documents/course/1"]:
        assert client.get(path).location.endswith("/change-password")
    assert (
        client.post(
            "/change-password",
            data={"new_password": "short", "email": "pupil@example.fr"},
        ).status_code
        == 400
    )
    assert (
        client.post(
            "/change-password", data={"new_password": "NewPassword123", "email": ""}
        ).status_code
        == 400
    )
    assert (
        client.post(
            "/change-password",
            data={"new_password": "NewPassword123", "email": "invalid"},
        ).status_code
        == 400
    )
    assert (
        client.post(
            "/change-password",
            data={"new_password": "NewPassword123", "email": "pupil@example.fr"},
        ).status_code
        == 302
    )
    assert client.get("/jsp").status_code == 200


def test_regular_password_change_requires_current_password(app, client):
    login(client, "pupil")
    assert (
        client.post(
            "/change-password",
            data={
                "new_password": "NewPassword123",
                "email": "pupil@example.fr",
                "current_password": "bad",
            },
        ).status_code
        == 400
    )
    assert (
        client.post(
            "/change-password",
            data={
                "new_password": "NewPassword123",
                "email": "pupil@example.fr",
                "current_password": "TestPassword123",
            },
        ).status_code
        == 302
    )
    assert client.get("/jsp").status_code == 200


def test_revoked_sessions(app, client):
    other = app.test_client()
    login(client, "pupil")
    login(other, "pupil")
    client.post(
        "/change-password",
        data={
            "new_password": "NewPassword123",
            "email": "pupil@example.fr",
            "current_password": "TestPassword123",
        },
    )
    assert other.get("/jsp").status_code == 302


def test_profile_validation(app, client):
    login(client, "pupil")
    assert (
        client.post(
            "/profile", data={"prenom": "P", "nom": "N", "email": "teacher@example.fr"}
        ).status_code
        == 400
    )
    assert (
        client.post(
            "/profile", data={"prenom": "P", "nom": "N", "email": "new@example.fr"}
        ).status_code
        == 302
    )
    assert "new@example.fr" in client.get("/profile").text


def test_no_fake_reset(app, client):
    with app.app_context():
        old = User.query.filter_by(username="pupil").one().password_hash
    response = client.post(
        "/forgot-password", data={"email": "pupil@example.fr"}, follow_redirects=True
    )
    assert "pas configurée" in response.text
    with app.app_context():
        assert User.query.filter_by(username="pupil").one().password_hash == old


def test_reset_link_one_use(app, client):
    with app.app_context():
        u = User.query.filter_by(username="pupil").one()
        token = URLSafeTimedSerializer(app.secret_key).dumps(
            {"id": u.id, "version": u.auth_version}, salt="password-reset"
        )
    assert client.get("/reset-password/" + token).status_code == 200
    assert (
        client.post(
            "/reset-password/" + token, data={"new_password": "ResetPassword123"}
        ).status_code
        == 302
    )
    assert client.get("/reset-password/" + token).status_code == 400
    assert client.get("/reset-password/invalid").status_code == 400
    with app.app_context():
        assert check_password_hash(
            User.query.filter_by(username="pupil").one().password_hash,
            "ResetPassword123",
        )


def test_expired_reset(app, client):
    with app.app_context():
        u = User.query.filter_by(username="pupil").one()
        with patch("itsdangerous.timed.time.time", return_value=1):
            token = URLSafeTimedSerializer(app.secret_key).dumps(
                {"id": u.id, "version": u.auth_version}, salt="password-reset"
            )
    assert client.get("/reset-password/" + token).status_code == 400


def test_smtp_delivery_without_real_send(app, client):
    app.config.update(SMTP_HOST="smtp.example", SMTP_FROM="portal@example.fr")
    with patch("app.smtplib.SMTP") as smtp:
        response = client.post(
            "/forgot-password",
            data={"email": "pupil@example.fr"},
            follow_redirects=True,
        )
        message = smtp.return_value.__enter__.return_value.send_message.call_args.args[
            0
        ]
        assert (
            message["To"] == "pupil@example.fr"
            and "https://portal.example.fr/reset-password/" in message.get_content()
        )
        assert "Si un compte unique" in response.text
    with app.app_context():
        assert check_password_hash(
            User.query.filter_by(username="pupil").one().password_hash,
            "TestPassword123",
        )


def test_smtp_failure(app, client):
    app.config.update(SMTP_HOST="smtp.example", SMTP_FROM="portal@example.fr")
    with patch("app.smtplib.SMTP", side_effect=OSError):
        response = client.post(
            "/forgot-password",
            data={"email": "pupil@example.fr"},
            follow_redirects=True,
        )
        assert "indisponible" in response.text


def test_admin_create_user_level_and_unique_password(app, client):
    login(client, "admin")
    data = {
        "username": "new",
        "role": "jsp",
        "nom": "New",
        "prenom": "Test",
        "section_id": "1",
        "level": "JSP 3",
    }
    response = client.post("/admin/create-user", data=data, follow_redirects=True)
    assert response.status_code == 200 and "Mot de passe provisoire" in response.text
    with app.app_context():
        u = User.query.filter_by(username="new").one()
        assert u.level == "JSP 3" and u.first_login
        assert not check_password_hash(u.password_hash, "JSPinit2026")
    assert (
        client.post("/admin/create-user", data={**data, "username": "NEW"}).status_code
        == 400
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"role": "admin"},
        {"role": "fake"},
        {"level": "JSP 99"},
        {"section_id": "junk"},
        {"section_id": "99"},
        {"username": ""},
    ],
)
def test_invalid_admin_user(client, changes):
    login(client, "admin")
    r = client.post(
        "/admin/create-user",
        data={
            "username": "new",
            "role": "jsp",
            "nom": "N",
            "prenom": "P",
            "section_id": "1",
            "level": "JSP 1",
            **changes,
        },
    )
    assert r.status_code in {400, 404}


def test_permissions(client):
    login(client, "pupil")
    assert client.get("/admin/sections").status_code == 403
    assert client.post("/admin/create-user").status_code == 403
    assert client.post("/formateur/create-event").status_code == 403


def test_admin_section_selection(client):
    login(client, "admin")
    assert client.get("/formateur").status_code == 403
    assert client.post("/admin/section/1").status_code == 302
    assert client.get("/formateur").status_code == 200


def test_event_targeting_and_responses(app, client):
    login(client)
    create_event(client)
    with app.app_context():
        ev = db.session.get(Event, 1)
        assert {r.jsp.username for r in ev.responses} == {
            "teacher",
            "teacher2",
            "pupil",
        }
    client.post("/logout")
    login(client, "pupil2")
    assert "Test exercice" not in client.get("/jsp").text
    assert (
        client.post("/jsp/respond-event/1", data={"status": "present"}).status_code
        == 403
    )
    client.post("/logout")
    login(client, "pupil")
    assert (
        client.post("/jsp/respond-event/1", data={"status": "present"}).status_code
        == 302
    )
    assert (
        client.post("/jsp/respond-event/1", data={"status": "hack"}).status_code == 400
    )
    with app.app_context():
        assert (
            EventResponse.query.filter_by(
                event_id=1, jsp_id=User.query.filter_by(username="pupil").one().id
            )
            .one()
            .status
            == "present"
        )


def test_edit_event_reconciles_participants(app, client):
    login(client)
    create_event(client)
    assert (
        client.post(
            "/formateur/edit-event/1",
            data={
                "title": "Modified",
                "date_time": "2026-11-12T14:00",
                "target_level": "JSP 2",
            },
        ).status_code
        == 302
    )
    with app.app_context():
        ev = db.session.get(Event, 1)
        assert ev.end_time is None
        assert {r.jsp.username for r in ev.responses} == {
            "teacher",
            "teacher2",
            "pupil2",
        }
    assert client.get("/formateur").status_code == 200


def test_later_account_gets_only_targeted_responses(app, client):
    login(client)
    create_event(client, target="JSP 2")
    client.post("/logout")
    login(client, "admin")
    for name, level in [("new1", "JSP 1"), ("new2", "JSP 2")]:
        client.post(
            "/admin/create-user",
            data={
                "username": name,
                "role": "jsp",
                "nom": "N",
                "prenom": "P",
                "section_id": "1",
                "level": level,
            },
        )
    with app.app_context():
        assert not User.query.filter_by(username="new1").one().event_responses
        assert len(User.query.filter_by(username="new2").one().event_responses) == 1


def test_level_change_updates_future_participation_preserves_grades(app, client):
    login(client)
    create_event(client, target="JSP 2")
    with app.app_context():
        uid = User.query.filter_by(username="pupil").one().id
    client.post(
        f"/formateur/add-grade/{uid}", data={"title": "Old grade", "score": "14"}
    )
    assert (
        client.post(
            f"/formateur/update-jsp-info/{uid}",
            data={"email": "pupil@example.fr", "level": "JSP 2", "centre": "CR"},
        ).status_code
        == 302
    )
    with app.app_context():
        u = db.session.get(User, uid)
        assert (
            u.grades[0].level_attained == "JSP 1"
            and len(u.event_responses) == 1
            and u.centre == "CR"
        )


@pytest.mark.parametrize(
    "changes",
    [
        {"date_time": "nonsense"},
        {"end_time": "2026-11-12T13:00"},
        {"target_level": "JSP 9"},
        {"event_type": "bad"},
        {"title": ""},
    ],
)
def test_event_validation(client, changes):
    login(client)
    response = client.post(
        "/formateur/create-event",
        data={
            "title": "Test",
            "date_time": "2026-11-12T14:00",
            "event_type": "seance",
            **changes,
        },
    )
    assert response.status_code == 400


def test_cross_section_event_blocked(app, client):
    login(client)
    create_event(client)
    client.post("/logout")
    login(client, "outsider", "2")
    assert client.post("/formateur/edit-event/1", data={}).status_code == 404
    assert client.post("/formateur/delete-event/1").status_code == 404
    assert (
        client.post("/jsp/respond-event/1", data={"status": "present"}).status_code
        == 404
    )


def test_event_delete_cascades(app, client):
    login(client)
    create_event(client)
    assert client.post("/formateur/delete-event/1").status_code == 302
    with app.app_context():
        assert Event.query.count() == 0 and EventResponse.query.count() == 0


def test_upload_download_delete_and_no_overwrite(app, client):
    login(client)
    assert upload(client).status_code == 302
    assert upload(client).status_code == 302
    with app.app_context():
        docs = Course.query.all()
        assert len({d.filename for d in docs}) == 2
        name = docs[0].filename
    assert client.get("/formateur").status_code == 200
    assert client.get("/documents/course/1").status_code == 200
    assert (
        "attachment" in client.get("/documents/course/1").headers["Content-Disposition"]
    )
    assert client.get("/static/uploads/" + name).status_code == 404
    assert client.post("/documents/course/1/delete").status_code == 302
    assert not (Path(app.config["UPLOAD_FOLDER"]) / name).exists()


@pytest.mark.parametrize(
    "filename,content",
    [
        ("bad.html", b"<script>"),
        ("bad.pdf", b"<script>"),
        ("empty.pdf", b""),
        ("bad.jpg", b"bad"),
        ("bad.docx", b"bad"),
    ],
)
def test_reject_invalid_files(app, client, filename, content):
    login(client)
    assert (
        client.post(
            "/formateur/upload-course",
            data={"title": "Bad", "file": (io.BytesIO(content), filename)},
            content_type="multipart/form-data",
        ).status_code
        == 400
    )
    assert not list(Path(app.config["UPLOAD_FOLDER"]).glob("*"))


def test_upload_limit(app, client):
    app.config["MAX_CONTENT_LENGTH"] = 1024
    login(client)
    assert (
        client.post(
            "/formateur/upload-course",
            data={
                "title": "Big",
                "file": (io.BytesIO(b"%PDF-" + b"x" * 3000), "big.pdf"),
            },
            content_type="multipart/form-data",
        ).status_code
        == 413
    )


def test_private_document_recipient_and_section(app, client):
    login(client, "pupil")
    with app.app_context():
        tid = User.query.filter_by(username="teacher").one().id
        outsider = User.query.filter_by(username="outsider").one().id
    assert (
        upload(client, "/jsp/upload-doc", formateur_id=str(outsider)).status_code == 404
    )
    assert upload(client, "/jsp/upload-doc", formateur_id=str(tid)).status_code == 302
    assert client.get("/jsp").status_code == 200
    client.post("/logout")
    login(client, "pupil2")
    assert client.get("/documents/jsp/1").status_code == 404
    client.post("/logout")
    login(client, "teacher2")
    assert client.get("/documents/jsp/1").status_code == 404
    assert "Document test" not in client.get("/formateur").text
    client.post("/logout")
    login(client, "teacher")
    assert client.get("/documents/jsp/1").status_code == 200
    assert client.get("/formateur").status_code == 200
    client.post("/logout")
    login(client, "outsider", "2")
    assert client.get("/documents/jsp/1").status_code == 404


def test_course_not_accessible_other_section(client):
    login(client)
    upload(client)
    client.post("/logout")
    login(client, "outsider", "2")
    assert client.get("/documents/course/1").status_code == 404


@pytest.mark.parametrize("score", ["-1", "21", "NaN", "Infinity", "bad"])
def test_grade_validation(app, client, score):
    login(client)
    with app.app_context():
        uid = User.query.filter_by(username="pupil").one().id
    assert (
        client.post(
            f"/formateur/add-grade/{uid}", data={"title": "Test", "score": score}
        ).status_code
        == 400
    )


def test_all_additional_modules(app, client):
    login(client)
    with app.app_context():
        uid = User.query.filter_by(username="pupil").one().id
    assert (
        client.post(
            "/formateur/alertes", data={"title": "Info", "content": "Training moved"}
        ).status_code
        == 302
    )
    assert (
        client.post(
            "/formateur/equipment",
            data={"title": "Casques", "quantity": "12", "condition": "bon"},
        ).status_code
        == 302
    )
    assert (
        client.post(
            "/formateur/equipment/1", data={"quantity": "11", "condition": "a_verifier"}
        ).status_code
        == 302
    )
    assert (
        client.post(
            "/formateur/transactions",
            data={"title": "Cotisation", "amount": "20.50", "date": "2026-10-11"},
        ).status_code
        == 302
    )
    assert (
        client.post(
            "/formateur/transactions",
            data={"title": "Achat", "amount": "-5.25", "date": "2026-10-11"},
        ).status_code
        == 302
    )
    assert (
        client.post(
            f"/formateur/progress/{uid}", data={"title": "UE INC", "status": "valide"}
        ).status_code
        == 302
    )
    assert client.get("/formateur").status_code == 200
    assert "15.25" in client.get("/formateur").text
    client.post("/logout")
    login(client, "pupil")
    response = client.get("/jsp")
    assert (
        response.status_code == 200
        and "Training moved" in response.text
        and "UE INC" in response.text
    )
    assert "Cotisation" not in response.text


@pytest.mark.parametrize(
    "module,url,data",
    [
        ("calendrier", "/formateur/create-event", {"event_type": "calendrier"}),
        ("seances", "/formateur/create-event", {"event_type": "seance"}),
        ("fiches", "/formateur/update-jsp-info/4", {}),
        ("evaluations", "/formateur/add-grade/4", {}),
        ("evaluations", "/formateur/upload-eval", {}),
        ("cours", "/formateur/upload-course", {}),
        ("livret", "/formateur/progress/4", {}),
        ("materiel", "/formateur/equipment", {}),
        ("alerte", "/formateur/alertes", {}),
        ("tresorerie", "/formateur/transactions", {}),
    ],
)
def test_disabled_modules_server_checks(app, client, module, url, data):
    with app.app_context():
        setattr(db.session.get(Section, 1), "module_" + module, False)
        db.session.commit()
    login(client)
    assert client.post(url, data=data).status_code == 403
    assert f'id="{module}"' not in client.get("/formateur").text


def test_all_modules_disabled(app, client):
    with app.app_context():
        sec = db.session.get(Section, 1)
        for key in [
            "calendrier",
            "seances",
            "fiches",
            "evaluations",
            "cours",
            "livret",
            "materiel",
            "stats",
            "alerte",
            "tresorerie",
        ]:
            setattr(sec, "module_" + key, False)
        db.session.commit()
    login(client)
    assert "Aucun module activé" in client.get("/formateur").text
    client.post("/logout")
    login(client, "pupil")
    assert client.get("/jsp").status_code == 200


def test_section_delete_cascades_all_data_and_files(app, client):
    login(client)
    create_event(client)
    upload(client)
    upload(client, "/formateur/upload-eval")
    with app.app_context():
        user = User.query.filter_by(username="pupil").one()
        db.session.add_all(
            [
                Grade(jsp=user, title="Grade", score=15),
                Progress(jsp=user, title="Progress", level="JSP 1"),
                Equipment(title="Equipment", quantity=1, section_id=1),
                Transaction(
                    title="Donation",
                    amount=Decimal("10"),
                    date=date.today(),
                    section_id=1,
                ),
                Alerte(title="Info", content="Hello", section_id=1),
            ]
        )
        db.session.commit()
    client.post("/logout")
    login(client, "pupil")
    upload(client, "/jsp/upload-doc")
    client.post("/logout")
    login(client, "admin")
    assert client.post("/admin/delete-section/1").status_code == 302
    with app.app_context():
        for model in (
            Event,
            EventResponse,
            Grade,
            Course,
            Evaluation,
            JspDocument,
            Alerte,
            Progress,
            Equipment,
            Transaction,
        ):
            assert model.query.count() == 0
        assert User.query.count() == 3 and Section.query.count() == 1
    assert not list(Path(app.config["UPLOAD_FOLDER"]).glob("*"))


def test_delete_teacher_keeps_jsp_document(app, client):
    with app.app_context():
        tid = User.query.filter_by(username="teacher").one().id
    login(client, "pupil")
    upload(client, "/jsp/upload-doc", formateur_id=str(tid))
    client.post("/logout")
    login(client, "admin")
    assert client.post(f"/admin/delete-user/{tid}").status_code == 302
    with app.app_context():
        assert JspDocument.query.one().formateur_id is None


def test_cannot_delete_admin(app, client):
    login(client, "admin")
    with app.app_context():
        uid = User.query.filter_by(username="admin").one().id
    assert client.post(f"/admin/delete-user/{uid}").status_code == 400


def test_admin_reset_revokes_session(app, client):
    pupilclient = app.test_client()
    login(pupilclient, "pupil")
    login(client, "admin")
    with app.app_context():
        uid = User.query.filter_by(username="pupil").one().id
    assert client.post(f"/admin/reset-user/{uid}").status_code == 302
    assert pupilclient.get("/jsp").status_code == 302


def test_no_get_logout_and_csrf(app, client):
    app.config["WTF_CSRF_ENABLED"] = True
    assert (
        client.post(
            "/login",
            data={
                "username": "pupil",
                "password": "TestPassword123",
                "section_id": "1",
            },
        ).status_code
        == 400
    )
    response = client.get("/login")
    token = re.search(r'name="csrf_token" value="([^"]+)"', response.text).group(1)
    assert (
        client.post(
            "/login",
            data={
                "username": "pupil",
                "password": "TestPassword123",
                "section_id": "1",
                "csrf_token": token,
            },
        ).status_code
        == 302
    )
    assert client.get("/logout").status_code == 405
    assert client.post("/profile", data={"prenom": "P", "nom": "N"}).status_code == 400
    assert client.get("/jsp").headers["Cache-Control"] == "no-store"


def test_health_and_cli_idempotent(app, client):
    assert client.get("/health").json == {"status": "ok"}
    assert app.test_cli_runner().invoke(args=["init-db"]).exit_code == 0
    assert app.test_cli_runner().invoke(args=["init-db"]).exit_code == 0


def test_old_database_migration_preserves_account(tmp_path):
    app = create_app(
        {
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": "sqlite:///" + str(tmp_path / "old.db"),
            "UPLOAD_FOLDER": str(tmp_path / "uploads"),
        }
    )
    with app.app_context():
        db.create_all()
        # Reproduire la table user de l'archive avant l'ajout des deux champs.
        with db.engine.begin() as c:
            c.exec_driver_sql('ALTER TABLE "user" DROP COLUMN centre')
            c.exec_driver_sql('ALTER TABLE "user" DROP COLUMN auth_version')
            c.exec_driver_sql(
                "INSERT INTO user (username,password_hash,role,level,nom,prenom,first_login) VALUES ('legacy','unchanged','admin','N/A','Old','Account',0)"
            )
        initialize_database()
        initialize_database()
        user = User.query.filter_by(username="legacy").one()
        assert (
            user.password_hash == "unchanged"
            and user.auth_version == 1
            and user.nom == "Old"
        )


def test_reset_rate_limit(client):
    for _ in range(5):
        assert (
            client.post(
                "/forgot-password", data={"email": "pupil@example.fr"}
            ).status_code
            == 302
        )
    assert (
        client.post("/forgot-password", data={"email": "pupil@example.fr"}).status_code
        == 429
    )


def test_historical_presence_survives_level_change(app, client):
    login(client)
    response = client.post(
        "/formateur/create-event",
        data={
            "title": "Ancien exercice",
            "date_time": "2025-01-01T14:00",
            "target_level": "JSP 1",
        },
    )
    assert response.status_code == 302
    with app.app_context():
        uid = User.query.filter_by(username="pupil").one().id
    client.post(
        f"/formateur/update-jsp-info/{uid}",
        data={"email": "pupil@example.fr", "level": "JSP 2"},
    )
    with app.app_context():
        assert len(db.session.get(User, uid).event_responses) == 1
    client.post("/logout")
    login(client, "pupil")
    assert "Ancien exercice" in client.get("/jsp").text
    assert (
        client.post("/jsp/respond-event/1", data={"status": "present"}).status_code
        == 302
    )


def test_exports_and_formula_protection(app, client):
    login(client)
    client.post(
        "/formateur/transactions",
        data={"title": "=1+1", "amount": "-10.50", "date": "2026-10-11"},
    )
    response = client.get("/formateur/export-treasury")
    assert (
        response.status_code == 200
        and "'=1+1" in response.text
        and "-10.50" in response.text
    )
    assert client.get("/formateur/export-stats").status_code == 200
    client.post("/logout")
    login(client, "pupil")
    assert client.get("/formateur/export-stats").status_code == 403


def test_known_default_password_rotated(app):
    from werkzeug.security import generate_password_hash

    with app.app_context():
        admin = User.query.filter_by(username="admin").one()
        admin.password_hash = generate_password_hash("Admin2026!")
        db.session.commit()
    result = app.test_cli_runner().invoke(args=["init-db"])
    assert result.exit_code == 0 and "prédéfini remplacé" in result.output
    with app.app_context():
        admin = User.query.filter_by(username="admin").one()
        assert admin.first_login and not check_password_hash(
            admin.password_hash, "Admin2026!"
        )


@pytest.mark.parametrize(
    "path",
    [
        "/static/uploads/private.pdf",
        "/static/./uploads/private.pdf",
        "/static/x/../uploads/private.pdf",
        "/static/%75ploads/private.pdf",
    ],
)
def test_legacy_static_path_normalization_blocked(app, client, path, tmp_path):
    public = tmp_path / "static"
    (public / "uploads").mkdir(parents=True)
    (public / "uploads" / "private.pdf").write_bytes(b"%PDF-1.4 private")
    app.static_folder = str(public)
    assert client.get(path).status_code == 404


def test_refuse_public_upload_folder(tmp_path):
    with pytest.raises(RuntimeError, match="hors du dossier public"):
        create_app(
            {
                "TESTING": True,
                "SQLALCHEMY_DATABASE_URI": "sqlite:///" + str(tmp_path / "db.sqlite"),
                "UPLOAD_FOLDER": str(Path(__file__).parents[1] / "static" / "uploads"),
            }
        )
