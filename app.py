"""Portail JSP : application Flask et commandes d'installation."""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from functools import wraps
from io import StringIO
import csv
from hashlib import sha256
from pathlib import Path
import os
import secrets
import smtplib
from email.message import EmailMessage
import click
from dotenv import load_dotenv
from email_validator import validate_email, EmailNotValidError
from flask import (
    Flask,
    abort,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
    send_from_directory,
    Response,
)
from flask_login import (
    LoginManager,
    current_user,
    login_required,
    login_user,
    logout_user,
)
from flask_wtf.csrf import CSRFProtect, CSRFError
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from sqlalchemy import inspect, text, event as sql_event, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.engine import Engine
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename
from zoneinfo import ZoneInfo
from zipfile import ZipFile, BadZipFile
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
    RateAttempt,
)

BASE = Path(__file__).resolve().parent
LEVELS = ["JSP 1", "JSP 2", "JSP 3", "JSP 4"]
MODULES = {
    "calendrier": "Calendrier",
    "seances": "Séances & Présences",
    "fiches": "Fiches individuelles",
    "evaluations": "Évaluations",
    "cours": "Cours & Ressources",
    "livret": "Livret de progression",
    "materiel": "Matériel & EPI",
    "stats": "Statistiques",
    "alerte": "Alertes",
    "tresorerie": "Trésorerie & Cotisations",
}
login_manager = LoginManager()
csrf = CSRFProtect()


@sql_event.listens_for(Engine, "connect")
def sqlite_foreign_keys(connection, record):
    if connection.__class__.__module__.startswith("sqlite3"):
        connection.execute("PRAGMA foreign_keys=ON")


def initialize_database():
    """Migration additive de l'archive d'origine, sans effacer les données."""
    inspector = inspect(db.engine)
    if "user" in inspector.get_table_names():
        columns = {c["name"] for c in inspector.get_columns("user")}
        with db.engine.begin() as connection:
            if "centre" not in columns:
                connection.execute(
                    text(
                        "ALTER TABLE \"user\" ADD COLUMN centre VARCHAR(100) DEFAULT ''"
                    )
                )
            if "auth_version" not in columns:
                connection.execute(
                    text(
                        'ALTER TABLE "user" ADD COLUMN auth_version INTEGER NOT NULL DEFAULT 1'
                    )
                )
    db.create_all()
    # Les anciennes bases n'avaient aucune unicité des réponses.
    for ev in Event.query.all():
        seen = set()
        for response in sorted(ev.responses, key=lambda r: r.id):
            if response.jsp_id in seen:
                db.session.delete(response)
            seen.add(response.jsp_id)
    db.session.commit()
    with db.engine.begin() as connection:
        connection.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_response_event_user_idx ON event_response (event_id, jsp_id)"
            )
        )
        # L'identifiant était déjà traité sans tenir compte de la casse à la connexion.
        duplicates = connection.execute(
            text(
                'SELECT lower(username) FROM "user" GROUP BY lower(username) HAVING count(*) > 1'
            )
        ).all()
        if duplicates:
            raise click.ClickException(
                "Des identifiants ne diffèrent que par la casse. Renommez-les avant la migration."
            )
        connection.execute(
            text(
                'CREATE UNIQUE INDEX IF NOT EXISTS uq_user_username_lower ON "user" (lower(username))'
            )
        )
    if not Section.query.first():
        db.session.add(Section(nom="Section St Germain / Château-Renard"))
        db.session.commit()


def create_app(test_config=None):
    load_dotenv(BASE / ".env")
    app = Flask(__name__, instance_path=str(BASE / "instance"))
    Path(app.instance_path).mkdir(parents=True, exist_ok=True)
    secret = os.environ.get("SECRET_KEY", "").strip()
    production = os.environ.get("APP_ENV") == "production"
    if production and secret and len(secret) < 32:
        raise RuntimeError(
            "SECRET_KEY doit contenir au moins 32 caractères en production."
        )
    if not secret:
        if production:
            raise RuntimeError("SECRET_KEY est obligatoire en production.")
        secret_path = Path(app.instance_path) / "secret.key"
        try:
            with secret_path.open("x") as f:
                f.write(secrets.token_hex(32))
            secret_path.chmod(0o600)
        except FileExistsError:
            pass
        secret = secret_path.read_text().strip()
    db_url = os.environ.get("DATABASE_URL") or "sqlite:///caserne.db"
    for prefix in ("postgres://", "postgresql://"):
        if db_url.startswith(prefix):
            db_url = db_url.replace(prefix, "postgresql+pg8000://", 1)
            break
    app.config.update(
        SECRET_KEY=secret,
        SQLALCHEMY_DATABASE_URI=db_url,
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        SQLALCHEMY_ENGINE_OPTIONS={"pool_pre_ping": True},
        UPLOAD_FOLDER=os.environ.get("UPLOAD_FOLDER")
        or str(BASE / "instance" / "uploads"),
        MAX_CONTENT_LENGTH=20 * 1024 * 1024,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=production,
        PERMANENT_SESSION_LIFETIME=timedelta(hours=12),
        PUBLIC_URL=os.environ.get("PUBLIC_URL", "").rstrip("/"),
        SMTP_HOST=os.environ.get("SMTP_HOST", ""),
        SMTP_PORT=int(os.environ.get("SMTP_PORT", "587")),
        SMTP_USERNAME=os.environ.get("SMTP_USERNAME", ""),
        SMTP_PASSWORD=os.environ.get("SMTP_PASSWORD", ""),
        SMTP_FROM=os.environ.get("SMTP_FROM", ""),
        SMTP_TLS=os.environ.get("SMTP_TLS", "true").lower() == "true",
        SMTP_SSL=os.environ.get("SMTP_SSL", "false").lower() == "true",
    )
    if test_config:
        app.config.update(test_config)
    app.config["UPLOAD_FOLDER"] = str(Path(app.config["UPLOAD_FOLDER"]).resolve())
    if Path(app.config["UPLOAD_FOLDER"]).is_relative_to(
        Path(app.static_folder).resolve()
    ):
        raise RuntimeError(
            "UPLOAD_FOLDER doit se trouver hors du dossier public static."
        )
    Path(app.config["UPLOAD_FOLDER"]).mkdir(parents=True, exist_ok=True)
    db.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = "login"
    login_manager.login_message = "Veuillez vous connecter."
    csrf.init_app(app)
    register_routes(app)

    @app.before_request
    def first_login():
        if request.endpoint == "static" and (
            Path(app.static_folder) / (request.view_args or {}).get("filename", "")
        ).resolve().is_relative_to((Path(app.static_folder) / "uploads").resolve()):
            abort(
                404
            )  # Les anciens liens publics ne doivent plus servir des documents.
        if (
            current_user.is_authenticated
            and current_user.first_login
            and request.endpoint not in {"change_password", "logout", "static"}
        ):
            return redirect(url_for("change_password"))

    @app.after_request
    def security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        response.headers["Referrer-Policy"] = "same-origin"
        if current_user.is_authenticated or request.endpoint in {
            "login",
            "forgot_password",
            "reset_password",
        }:
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.errorhandler(CSRFError)
    def csrf_error(error):
        return render_template(
            "error.html",
            message="Formulaire expiré. Rechargez la page puis recommencez.",
        ), 400

    @app.errorhandler(IntegrityError)
    def constraint_error(error):
        db.session.rollback()
        return render_template(
            "error.html",
            message="Cette opération entre en conflit avec une donnée existante.",
        ), 409

    @app.errorhandler(ValueError)
    def validation_error(error):
        db.session.rollback()
        return render_template("error.html", message=str(error)), 400

    for code, message in [
        (403, "Accès non autorisé ou module désactivé."),
        (404, "La ressource demandée est introuvable."),
        (413, "Fichier trop volumineux : limite de 20 Mo."),
        (429, "Trop de tentatives. Réessayez dans 15 minutes."),
    ]:
        app.register_error_handler(
            code,
            lambda error, message=message, code=code: (
                render_template("error.html", message=message),
                code,
            ),
        )

    @app.context_processor
    def template_context():
        return {"levels": LEVELS, "modules": MODULES}

    @app.cli.command("init-db")
    def init_db():
        """Créer/migrer les tables et créer le premier admin si nécessaire."""
        initialize_database()
        if not User.query.filter_by(role="admin").first():
            password = os.environ.get("ADMIN_PASSWORD") or secrets.token_urlsafe(18)
            if len(password) < 10:
                raise click.ClickException(
                    "ADMIN_PASSWORD doit contenir au moins 10 caractères."
                )
            db.session.add(
                User(
                    username="admin",
                    password_hash=generate_password_hash(password),
                    role="admin",
                    prenom="Super",
                    nom="Admin",
                    first_login=True,
                )
            )
            db.session.commit()
            click.echo(
                f"Premier compte : admin / {password}\nConservez ce mot de passe provisoire dans un endroit sûr."
            )
        for user in User.query.all():
            if any(
                check_password_hash(user.password_hash, known)
                for known in ("Admin2026!", "JSPinit2026", "JSP2026!")
            ):
                password = secrets.token_urlsafe(18)
                set_password(user, password)
                user.first_login = True
                click.echo(
                    f"Ancien mot de passe prédéfini remplacé : {user.username} / {password}"
                )
        db.session.commit()
        click.echo("Base initialisée et migration terminée.")

    @app.cli.command("reset-admin-password")
    @click.option("--username", default="admin")
    @click.password_option(confirmation_prompt=True)
    def reset_admin_password(username, password):
        user = User.query.filter_by(username=username, role="admin").first()
        if not user or len(password) < 10:
            raise click.ClickException(
                "Compte absent ou mot de passe trop court (10 caractères minimum)."
            )
        set_password(user, password)
        user.first_login = True
        db.session.commit()
        click.echo("Mot de passe administrateur réinitialisé.")

    @app.cli.command("migrate-uploads")
    def migrate_uploads():
        """Déplacer les anciens fichiers hors du répertoire public."""
        import shutil

        old = BASE / "static" / "uploads"
        target = Path(app.config["UPLOAD_FOLDER"])
        for file in old.glob("*"):
            if file.is_file():
                dest = target / file.name
                if dest.exists():
                    raise click.ClickException(
                        f"Collision : {file.name}. Aucun écrasement effectué."
                    )
                shutil.move(str(file), str(dest))
        click.echo("Anciens documents déplacés.")

    return app


@login_manager.user_loader
def load_user(user_id):
    try:
        identity, version = user_id.split(":")
        user = db.session.get(User, int(identity))
        return user if user and user.auth_version == int(version) else None
    except (ValueError, TypeError):
        return None


def active_section():
    if current_user.role == "admin":
        sec = (
            db.session.get(Section, session.get("admin_section"))
            if session.get("admin_section")
            else None
        )
    else:
        sec = current_user.section
    if sec is None:
        abort(403)
    return sec


def access(role=None, module=None):
    def decorator(function):
        @wraps(function)
        @login_required
        def protected(*args, **kwargs):
            if role == "admin" and current_user.role != "admin":
                abort(403)
            if role == "formateur" and current_user.role not in {"admin", "formateur"}:
                abort(403)
            if role == "jsp" and current_user.role != "jsp":
                abort(403)
            if module and not getattr(active_section(), "module_" + module):
                abort(403)
            return function(*args, **kwargs)

        return protected

    return decorator


def field(name, maximum=150, required=True):
    value = request.form.get(name, "").strip()
    if (required and not value) or len(value) > maximum:
        raise ValueError(f"Champ {name} manquant ou trop long (maximum {maximum}).")
    return value


def email_value(value, required=False, user=None):
    value = (value or "").strip()
    if not value and not required:
        return None
    try:
        value = validate_email(value, check_deliverability=False).normalized
    except EmailNotValidError:
        raise ValueError("Adresse e-mail invalide.") from None
    if len(value) > 120:
        raise ValueError("Adresse e-mail trop longue.")
    query = User.query.filter(db.func.lower(User.email) == value.lower())
    if user:
        query = query.filter(User.id != user.id)
    if query.first():
        raise ValueError("Cette adresse e-mail est déjà utilisée.")
    return value


def set_password(user, password):
    if not password or not 10 <= len(password) <= 128:
        raise ValueError("Mot de passe : entre 10 et 128 caractères.")
    user.password_hash = generate_password_hash(password)
    user.auth_version += 1


def local_now():
    return datetime.now(ZoneInfo("Europe/Paris")).replace(tzinfo=None)


def invited(user, ev):
    return eligible(user, ev) or (
        user.section_id == ev.section_id
        and ev.date_time < local_now()
        and any(r.jsp_id == user.id for r in ev.responses)
    )


def eligible(user, ev):
    return user.section_id == ev.section_id and (
        user.role == "formateur"
        or (user.role == "jsp" and ev.target_level in {"Tous", user.level})
    )


def synchronize_responses(ev):
    users = User.query.filter_by(section_id=ev.section_id).all()
    desired = {u.id for u in users if eligible(u, ev)}
    existing = {r.jsp_id: r for r in ev.responses}
    for identity, response in existing.items():
        if identity not in desired:
            db.session.delete(response)
    for identity in desired - existing.keys():
        db.session.add(EventResponse(event=ev, jsp_id=identity))


def scoped(model, identity):
    obj = db.get_or_404(model, identity)
    sec_id = (
        obj.jsp.section_id
        if isinstance(obj, (Grade, JspDocument, Progress))
        else obj.section_id
    )
    if sec_id != active_section().id:
        abort(404)
    return obj


def dashboard_redirect():
    return redirect(
        url_for(
            "dashboard_jsp" if current_user.role == "jsp" else "dashboard_formateur"
        )
    )


def consume_rate(bucket, limit=10):
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    key = sha256(f"{bucket}:{request.remote_addr}".encode()).hexdigest()
    RateAttempt.query.filter(RateAttempt.expires < now).delete()
    record = db.session.get(RateAttempt, key)
    if not record:
        db.session.add(
            RateAttempt(key=key, count=1, expires=now + timedelta(minutes=15))
        )
        db.session.commit()
        return
    if record.count >= limit:
        abort(429)
    db.session.execute(
        update(RateAttempt)
        .where(RateAttempt.key == key)
        .values(count=RateAttempt.count + 1)
    )
    db.session.commit()


def save_upload():
    file = request.files.get("file")
    if not file or not file.filename:
        raise ValueError("Choisissez un fichier.")
    name = secure_filename(file.filename)
    suffix = Path(name).suffix.lower()
    if suffix not in {
        ".pdf",
        ".png",
        ".jpg",
        ".jpeg",
        ".docx",
        ".pptx",
        ".xlsx",
        ".txt",
    }:
        raise ValueError("Format autorisé : PDF, PNG, JPG, DOCX, PPTX, XLSX ou TXT.")
    prefix = file.stream.read(16)
    file.stream.seek(0)
    if not prefix:
        raise ValueError("Le fichier est vide.")
    if suffix == ".pdf" and not prefix.startswith(b"%PDF-"):
        raise ValueError("Ce fichier ne contient pas un PDF.")
    if suffix in {".docx", ".pptx", ".xlsx"}:
        required = {
            ".docx": "word/document.xml",
            ".pptx": "ppt/presentation.xml",
            ".xlsx": "xl/workbook.xml",
        }[suffix]
        try:
            with ZipFile(file.stream) as archive:
                if (
                    required not in archive.namelist()
                    or "[Content_Types].xml" not in archive.namelist()
                ):
                    raise ValueError("Document Office invalide.")
        except BadZipFile:
            raise ValueError("Document Office invalide.") from None
        finally:
            file.stream.seek(0)
    if suffix in {".png", ".jpg", ".jpeg"}:
        from PIL import Image, UnidentifiedImageError

        try:
            image = Image.open(file.stream)
            image.verify()
            if image.format not in {"PNG", "JPEG"}:
                raise ValueError("Image invalide.")
        except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
            raise ValueError("Image invalide.") from None
        finally:
            file.stream.seek(0)
    filename = secrets.token_hex(16) + suffix
    file.save(Path(current_app.config["UPLOAD_FOLDER"]) / filename)
    return filename


def commit_uploaded(model, **values):
    filename = save_upload()
    try:
        db.session.add(model(filename=filename, **values))
        db.session.commit()
    except Exception:
        db.session.rollback()
        (Path(current_app.config["UPLOAD_FOLDER"]) / filename).unlink(missing_ok=True)
        raise


def remove_files(filenames):
    for filename in filenames:
        if not any(
            model.query.filter_by(filename=filename).first()
            for model in (Course, Evaluation, JspDocument)
        ):
            path = Path(current_app.config["UPLOAD_FOLDER"]) / Path(filename).name
            try:
                path.unlink(missing_ok=True)
            except OSError:
                current_app.logger.warning("Nettoyage de document impossible.")


def register_routes(app):
    @app.route("/")
    def index():
        if not current_user.is_authenticated:
            return redirect(url_for("login"))
        return redirect(
            url_for(
                {
                    "admin": "manage_sections",
                    "formateur": "dashboard_formateur",
                    "jsp": "dashboard_jsp",
                }[current_user.role]
            )
        )

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if current_user.is_authenticated:
            return redirect(url_for("index"))
        if request.method == "POST":
            consume_rate(
                "login:" + request.form.get("username", "").strip().lower(), 20
            )
            username = request.form.get("username", "").strip()
            password = request.form.get("password", "")
            user = User.query.filter(
                db.func.lower(User.username) == username.lower()
            ).first()
            if (
                user
                and password
                and check_password_hash(user.password_hash, password)
                and (
                    user.role == "admin"
                    or str(user.section_id) == request.form.get("section_id")
                )
            ):
                session.clear()
                login_user(user)
                session.permanent = True
                return redirect(url_for("index"))
            flash("Identifiant, mot de passe ou section incorrect.", "danger")
        return render_template(
            "login.html", sections=Section.query.order_by(Section.nom).all()
        )

    @app.route("/logout", methods=["POST"])
    @login_required
    def logout():
        logout_user()
        session.clear()
        return redirect(url_for("login"))

    @app.route("/profile", methods=["GET", "POST"])
    @login_required
    def profile():
        if request.method == "POST":
            email = email_value(request.form.get("email"), user=current_user)
            prenom = field("prenom", 80)
            nom = field("nom", 80)
            current_user.prenom = prenom
            current_user.nom = nom
            current_user.email = email
            db.session.commit()
            flash("Profil mis à jour.", "success")
            return redirect(url_for("profile"))
        return render_template("profile.html")

    @app.route("/change-password", methods=["GET", "POST"])
    @login_required
    def change_password():
        if request.method == "POST":
            if not current_user.first_login and not check_password_hash(
                current_user.password_hash, request.form.get("current_password", "")
            ):
                raise ValueError("Mot de passe actuel incorrect.")
            email = email_value(
                request.form.get("email"), required=True, user=current_user
            )
            set_password(current_user, request.form.get("new_password"))
            current_user.email = email
            current_user.first_login = False
            db.session.commit()
            login_user(current_user._get_current_object())
            flash("Mot de passe mis à jour.", "success")
            return redirect(url_for("index"))
        return render_template("change_password.html")

    @app.route("/forgot-password", methods=["GET", "POST"])
    def forgot_password():
        if request.method == "POST":
            consume_rate("reset", 5)
            if not (
                app.config["SMTP_HOST"]
                and app.config["SMTP_FROM"]
                and app.config["PUBLIC_URL"]
            ):
                flash(
                    "La récupération par e-mail n’est pas configurée. Contactez votre administrateur.",
                    "warning",
                )
                return redirect(url_for("forgot_password"))
            email = request.form.get("email", "").strip()
            users = User.query.filter(db.func.lower(User.email) == email.lower()).all()
            if len(users) == 1:
                user = users[0]
                token = URLSafeTimedSerializer(app.secret_key).dumps(
                    {"id": user.id, "version": user.auth_version}, salt="password-reset"
                )
                link = app.config["PUBLIC_URL"] + url_for("reset_password", token=token)
                message = EmailMessage()
                message["Subject"] = "Caserne JSP – réinitialiser votre mot de passe"
                message["From"] = app.config["SMTP_FROM"]
                message["To"] = user.email
                message.set_content(
                    f"Pour définir un nouveau mot de passe, ouvrez ce lien (valable 30 minutes) :\n{link}\nSi vous n’avez pas fait cette demande, ignorez ce message."
                )
                try:
                    client = (
                        smtplib.SMTP_SSL if app.config["SMTP_SSL"] else smtplib.SMTP
                    )
                    with client(
                        app.config["SMTP_HOST"], app.config["SMTP_PORT"], timeout=10
                    ) as smtp:
                        if app.config["SMTP_TLS"] and not app.config["SMTP_SSL"]:
                            smtp.starttls()
                        if app.config["SMTP_USERNAME"]:
                            smtp.login(
                                app.config["SMTP_USERNAME"], app.config["SMTP_PASSWORD"]
                            )
                        smtp.send_message(message)
                except (OSError, smtplib.SMTPException):
                    app.logger.error(
                        "Envoi de récupération impossible (configuration SMTP à vérifier)."
                    )
                    flash(
                        "Le service e-mail est indisponible. Réessayez plus tard ou contactez votre administrateur.",
                        "warning",
                    )
                    return redirect(url_for("forgot_password"))
            flash(
                "Si un compte unique correspond à cette adresse, un lien de récupération a été envoyé.",
                "info",
            )
            return redirect(url_for("login"))
        return render_template("forgot_password.html")

    @app.route("/reset-password/<token>", methods=["GET", "POST"])
    def reset_password(token):
        try:
            payload = URLSafeTimedSerializer(app.secret_key).loads(
                token, salt="password-reset", max_age=1800
            )
            user = db.session.get(User, payload["id"])
            if not user or user.auth_version != payload["version"]:
                raise BadSignature("revoked")
        except (BadSignature, SignatureExpired, KeyError, TypeError):
            return render_template(
                "error.html", message="Lien invalide, expiré ou déjà utilisé."
            ), 400
        if request.method == "POST":
            set_password(user, request.form.get("new_password"))
            # Un compte provisoire doit encore renseigner/vérifier son email après connexion.
            db.session.commit()
            flash("Mot de passe réinitialisé. Vous pouvez vous connecter.", "success")
            return redirect(url_for("login"))
        return render_template("reset_password.html")

    @app.route("/admin/sections", methods=["GET", "POST"])
    @access("admin")
    def manage_sections():
        if request.method == "POST":
            action = request.form.get("action")
            if action == "create_section":
                db.session.add(Section(nom=field("nom", 100)))
            elif action == "toggle_modules":
                section_id = request.form.get("section_id", type=int)
                if section_id is None:
                    raise ValueError("Section invalide.")
                sec = db.get_or_404(Section, section_id)
                for module in MODULES:
                    setattr(sec, "module_" + module, "module_" + module in request.form)
            else:
                raise ValueError("Action inconnue.")
            db.session.commit()
            flash("Section enregistrée.", "success")
            return redirect(url_for("manage_sections"))
        return render_template(
            "manage_sections.html",
            sections=Section.query.order_by(Section.nom).all(),
            users=User.query.order_by(User.nom).all(),
        )

    @app.route("/admin/section/<int:section_id>", methods=["POST"])
    @access("admin")
    def select_section(section_id):
        db.get_or_404(Section, section_id)
        session["admin_section"] = section_id
        return redirect(url_for("dashboard_formateur"))

    @app.route("/admin/create-user", methods=["POST"])
    @access("admin")
    def admin_create_user():
        username = field("username", 80)
        role = field("role", 20)
        if role not in {"formateur", "jsp"}:
            raise ValueError("Rôle invalide.")
        section_id = request.form.get("section_id", type=int)
        if section_id is None:
            raise ValueError("Section invalide.")
        sec = db.get_or_404(Section, section_id)
        level = request.form.get("level", "JSP 1") if role == "jsp" else "N/A"
        if role == "jsp" and level not in LEVELS:
            raise ValueError("Niveau invalide.")
        if User.query.filter(db.func.lower(User.username) == username.lower()).first():
            raise ValueError("Cet identifiant existe déjà.")
        password = secrets.token_urlsafe(12)
        user = User(
            username=username,
            password_hash=generate_password_hash(password),
            role=role,
            level=level,
            nom=field("nom", 80),
            prenom=field("prenom", 80),
            section_id=sec.id,
            first_login=True,
        )
        db.session.add(user)
        db.session.flush()
        for ev in sec.events:
            if ev.date_time >= local_now() and eligible(user, ev):
                db.session.add(EventResponse(event=ev, jsp=user))
        db.session.commit()
        flash(
            f"Compte {username} créé. Mot de passe provisoire : {password}. À transmettre personnellement à son titulaire.",
            "success",
        )
        return redirect(url_for("manage_sections"))

    @app.route("/admin/reset-user/<int:user_id>", methods=["POST"])
    @access("admin")
    def admin_reset_user(user_id):
        user = db.get_or_404(User, user_id)
        password = secrets.token_urlsafe(12)
        set_password(user, password)
        user.first_login = True
        db.session.commit()
        if user.id == current_user.id:
            login_user(user)
        flash(f"Mot de passe provisoire de {user.username} : {password}", "warning")
        return redirect(url_for("manage_sections"))

    @app.route("/admin/delete-user/<int:user_id>", methods=["POST"])
    @access("admin")
    def delete_user(user_id):
        user = db.get_or_404(User, user_id)
        if user.id == current_user.id or user.role == "admin":
            raise ValueError("Un compte administrateur ne peut pas être supprimé ici.")
        files = [doc.filename for doc in user.jsp_docs]
        db.session.delete(user)
        db.session.commit()
        remove_files(files)
        flash("Compte supprimé.", "success")
        return redirect(url_for("manage_sections"))

    @app.route("/admin/delete-section/<int:section_id>", methods=["POST"])
    @access("admin")
    def delete_section(section_id):
        sec = db.get_or_404(Section, section_id)
        if any(u.role == "admin" for u in sec.users):
            raise ValueError(
                "Détachez les administrateurs de cette section avant de la supprimer."
            )
        files = [obj.filename for obj in sec.courses + sec.evaluations] + [
            doc.filename for user in sec.users for doc in user.jsp_docs
        ]
        db.session.delete(sec)
        db.session.commit()
        remove_files(files)
        if session.get("admin_section") == section_id:
            session.pop("admin_section")
        flash("Section et données associées supprimées.", "success")
        return redirect(url_for("manage_sections"))

    def dashboard_context(sec):
        events = [
            ev
            for ev in Event.query.filter_by(section_id=sec.id)
            .order_by(Event.date_time)
            .all()
            if getattr(
                sec,
                "module_"
                + ("calendrier" if ev.event_type == "calendrier" else "seances"),
            )
        ]
        if current_user.role == "jsp":
            events = [ev for ev in events if invited(current_user, ev)]
        return dict(
            sec=sec,
            events=events,
            courses=Course.query.filter_by(section_id=sec.id)
            .order_by(Course.upload_date.desc())
            .all()
            if sec.module_cours
            else [],
            evaluations=Evaluation.query.filter_by(section_id=sec.id)
            .order_by(Evaluation.upload_date.desc())
            .all()
            if sec.module_evaluations
            else [],
            alertes=Alerte.query.filter_by(section_id=sec.id)
            .order_by(Alerte.date_posted.desc())
            .all()
            if sec.module_alerte
            else [],
            jsps=User.query.filter_by(section_id=sec.id, role="jsp")
            .order_by(User.nom)
            .all(),
            formateurs=User.query.filter_by(section_id=sec.id, role="formateur")
            .order_by(User.nom)
            .all(),
            equipment=Equipment.query.filter_by(section_id=sec.id)
            .order_by(Equipment.title)
            .all()
            if sec.module_materiel
            else [],
            transactions=Transaction.query.filter_by(section_id=sec.id)
            .order_by(Transaction.date.desc())
            .all()
            if sec.module_tresorerie
            else [],
        )

    @app.route("/formateur")
    @access("formateur")
    def dashboard_formateur():
        context = dashboard_context(active_section())
        return render_template("dashboard_formateur.html", **context)

    @app.route("/jsp")
    @access("jsp")
    def dashboard_jsp():
        return render_template(
            "dashboard_jsp.html", **dashboard_context(active_section())
        )

    def event_values():
        title = field("title")
        description = field("description", 10000, False)
        location = field("location", 150, False)
        try:
            start = datetime.fromisoformat(request.form.get("date_time", ""))
            end = (
                datetime.fromisoformat(request.form["end_time"])
                if request.form.get("end_time")
                else None
            )
        except ValueError:
            raise ValueError("Date ou heure invalide.") from None
        if start.tzinfo or (end and end.tzinfo):
            raise ValueError("Utilisez une date et heure locale sans fuseau.")
        if end and end <= start:
            raise ValueError("La fin doit être après le début.")
        target = request.form.get("target_level", "Tous")
        if target not in ["Tous"] + LEVELS:
            raise ValueError("Niveau cible invalide.")
        return dict(
            title=title,
            description=description,
            location=location,
            date_time=start,
            end_time=end,
            target_level=target,
        )

    def event_access(ev):
        if not getattr(
            active_section(),
            "module_" + ("calendrier" if ev.event_type == "calendrier" else "seances"),
        ):
            abort(403)

    @app.route("/formateur/create-event", methods=["POST"])
    @access("formateur")
    def create_event():
        kind = request.form.get("event_type", "seance")
        if kind not in {"seance", "calendrier"}:
            raise ValueError("Type d’événement invalide.")
        sec = active_section()
        if not getattr(
            sec, "module_" + ("seances" if kind == "seance" else "calendrier")
        ):
            abort(403)
        ev = Event(
            **event_values(),
            event_type=kind,
            section_id=sec.id,
            created_by=f"{current_user.prenom} {current_user.nom}"[:80],
        )
        db.session.add(ev)
        db.session.flush()
        synchronize_responses(ev)
        db.session.commit()
        flash("Événement publié.", "success")
        return dashboard_redirect()

    @app.route("/formateur/edit-event/<int:event_id>", methods=["POST"])
    @access("formateur")
    def edit_event(event_id):
        ev = scoped(Event, event_id)
        event_access(ev)
        for key, value in event_values().items():
            setattr(ev, key, value)
        synchronize_responses(ev)
        db.session.commit()
        flash("Événement mis à jour.", "success")
        return dashboard_redirect()

    @app.route("/formateur/delete-event/<int:event_id>", methods=["POST"])
    @access("formateur")
    def delete_event(event_id):
        ev = scoped(Event, event_id)
        event_access(ev)
        db.session.delete(ev)
        db.session.commit()
        flash("Événement supprimé.", "success")
        return dashboard_redirect()

    @app.route("/jsp/respond-event/<int:event_id>", methods=["POST"])
    @login_required
    def respond_event(event_id):
        ev = scoped(Event, event_id)
        event_access(ev)
        if not invited(current_user, ev):
            abort(403)
        status = request.form.get("status")
        if status not in {"present", "absent", "en_attente"}:
            raise ValueError("Statut invalide.")
        response = EventResponse.query.filter_by(
            event_id=ev.id, jsp_id=current_user.id
        ).first()
        if not response:
            response = EventResponse(event=ev, jsp_id=current_user.id)
            db.session.add(response)
        response.status = status
        db.session.commit()
        flash("Réponse enregistrée.", "success")
        return dashboard_redirect()

    @app.route("/formateur/update-jsp-info/<int:jsp_id>", methods=["POST"])
    @access("formateur", "fiches")
    def update_jsp_info(jsp_id):
        user = db.get_or_404(User, jsp_id)
        if user.section_id != active_section().id or user.role == "admin":
            abort(404)
        if (
            current_user.role == "formateur"
            and user.role == "formateur"
            and user.id != current_user.id
        ):
            abort(403)
        email = email_value(request.form.get("email"), user=user)
        born = request.form.get("date_naissance", "")
        try:
            birthday = date.fromisoformat(born) if born else None
        except ValueError:
            raise ValueError("Date de naissance invalide.") from None
        if birthday and birthday > date.today():
            raise ValueError("Date de naissance future.")
        level = request.form.get("level", user.level)
        if user.role == "jsp" and level not in LEVELS:
            raise ValueError("Niveau invalide.")
        user.email = email
        user.date_naissance = birthday
        user.adresse = field("adresse", 200, False)
        user.centre = field("centre", 100, False)
        user.level = level
        for ev in user.section.events:
            if ev.date_time >= local_now():
                synchronize_responses(ev)
        db.session.commit()
        flash("Fiche mise à jour.", "success")
        return dashboard_redirect()

    @app.route("/formateur/add-grade/<int:jsp_id>", methods=["POST"])
    @access("formateur", "evaluations")
    def add_grade(jsp_id):
        user = db.get_or_404(User, jsp_id)
        if user.role != "jsp" or user.section_id != active_section().id:
            abort(404)
        try:
            score = Decimal(request.form.get("score", "").replace(",", "."))
        except InvalidOperation:
            raise ValueError("Note invalide.") from None
        if not score.is_finite() or not 0 <= score <= 20:
            raise ValueError("Note : entre 0 et 20.")
        db.session.add(
            Grade(
                jsp=user,
                title=field("title"),
                score=float(score),
                level_attained=user.level,
            )
        )
        db.session.commit()
        flash("Note enregistrée.", "success")
        return dashboard_redirect()

    @app.route("/formateur/delete-grade/<int:grade_id>", methods=["POST"])
    @access("formateur", "evaluations")
    def delete_grade(grade_id):
        db.session.delete(scoped(Grade, grade_id))
        db.session.commit()
        return dashboard_redirect()

    @app.route("/formateur/upload-course", methods=["POST"])
    @access("formateur", "cours")
    def upload_course():
        commit_uploaded(
            Course,
            title=field("title"),
            section_id=active_section().id,
            uploaded_by=f"{current_user.prenom} {current_user.nom}"[:80],
        )
        flash("Cours publié.", "success")
        return dashboard_redirect()

    @app.route("/formateur/upload-eval", methods=["POST"])
    @access("formateur", "evaluations")
    def upload_eval():
        commit_uploaded(
            Evaluation,
            title=field("title"),
            section_id=active_section().id,
            uploaded_by=f"{current_user.prenom} {current_user.nom}"[:80],
        )
        flash("Évaluation publiée.", "success")
        return dashboard_redirect()

    @app.route("/jsp/upload-doc", methods=["POST"])
    @access("jsp", "fiches")
    def jsp_upload_doc():
        recipient = request.form.get("formateur_id")
        if recipient:
            try:
                recipient = int(recipient)
            except ValueError:
                raise ValueError("Destinataire invalide.") from None
            user = db.get_or_404(User, recipient)
            if user.role != "formateur" or user.section_id != active_section().id:
                abort(404)
        commit_uploaded(
            JspDocument,
            title=field("title"),
            jsp_id=current_user.id,
            formateur_id=recipient or None,
            level_attained=current_user.level,
        )
        flash("Document transmis.", "success")
        return dashboard_redirect()

    def permitted_document(kind, identity):
        models = {
            "course": (Course, "cours"),
            "evaluation": (Evaluation, "evaluations"),
            "jsp": (JspDocument, "fiches"),
        }
        if kind not in models:
            abort(404)
        model, module = models[kind]
        doc = db.get_or_404(model, identity)
        sec = doc.jsp.section if kind == "jsp" else doc.section
        if not sec or not getattr(sec, "module_" + module):
            abort(403)
        if current_user.role == "admin":
            return doc
        if current_user.section_id != sec.id:
            abort(404)
        if kind == "jsp":
            if current_user.role == "jsp" and doc.jsp_id != current_user.id:
                abort(404)
            if current_user.role == "formateur" and doc.formateur_id not in {
                None,
                current_user.id,
            }:
                abort(404)
        return doc

    @app.route("/documents/<kind>/<int:document_id>")
    @login_required
    def download_document(kind, document_id):
        doc = permitted_document(kind, document_id)
        response = send_from_directory(
            app.config["UPLOAD_FOLDER"],
            doc.filename,
            as_attachment=True,
            download_name=secure_filename(doc.title) + Path(doc.filename).suffix,
        )
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.route("/documents/<kind>/<int:document_id>/delete", methods=["POST"])
    @login_required
    def delete_document(kind, document_id):
        doc = permitted_document(kind, document_id)
        if kind != "jsp" and current_user.role not in {"admin", "formateur"}:
            abort(403)
        filename = doc.filename
        db.session.delete(doc)
        db.session.commit()
        remove_files([filename])
        flash("Document supprimé.", "success")
        return dashboard_redirect()

    @app.route("/formateur/alertes", methods=["POST"])
    @access("formateur", "alerte")
    def create_alert():
        db.session.add(
            Alerte(
                title=field("title"),
                content=field("content", 10000),
                section_id=active_section().id,
            )
        )
        db.session.commit()
        flash("Alerte publiée dans le portail.", "success")
        return dashboard_redirect()

    @app.route("/formateur/progress/<int:jsp_id>", methods=["POST"])
    @access("formateur", "livret")
    def add_progress(jsp_id):
        user = db.get_or_404(User, jsp_id)
        if user.role != "jsp" or user.section_id != active_section().id:
            abort(404)
        status = request.form.get("status")
        if status not in {"en_cours", "valide", "a_revoir"}:
            raise ValueError("Statut de progression invalide.")
        db.session.add(
            Progress(jsp=user, title=field("title"), level=user.level, status=status)
        )
        db.session.commit()
        return dashboard_redirect()

    @app.route("/formateur/equipment", methods=["POST"])
    @access("formateur", "materiel")
    def add_equipment():
        quantity = request.form.get("quantity", type=int)
        condition = request.form.get("condition")
        if (
            quantity is None
            or not 0 <= quantity <= 100000
            or condition not in {"bon", "a_verifier", "hors_service"}
        ):
            raise ValueError("Quantité ou état invalide.")
        db.session.add(
            Equipment(
                title=field("title"),
                quantity=quantity,
                condition=condition,
                section_id=active_section().id,
            )
        )
        db.session.commit()
        return dashboard_redirect()

    @app.route("/formateur/equipment/<int:equipment_id>", methods=["POST"])
    @access("formateur", "materiel")
    def edit_equipment(equipment_id):
        item = scoped(Equipment, equipment_id)
        quantity = request.form.get("quantity", type=int)
        condition = request.form.get("condition")
        if (
            quantity is None
            or not 0 <= quantity <= 100000
            or condition not in {"bon", "a_verifier", "hors_service"}
        ):
            raise ValueError("Quantité ou état invalide.")
        item.quantity = quantity
        item.condition = condition
        db.session.commit()
        return dashboard_redirect()

    @app.route("/formateur/transactions", methods=["POST"])
    @access("formateur", "tresorerie")
    def add_transaction():
        try:
            amount = Decimal(request.form.get("amount", "").replace(",", "."))
            day = date.fromisoformat(request.form.get("date", ""))
        except (InvalidOperation, ValueError):
            raise ValueError("Montant ou date invalide.") from None
        if (
            not amount.is_finite()
            or amount == 0
            or abs(amount) >= Decimal("10000000000")
            or amount.as_tuple().exponent < -2
        ):
            raise ValueError("Montant non nul, avec deux décimales maximum.")
        db.session.add(
            Transaction(
                title=field("title"),
                amount=amount,
                date=day,
                section_id=active_section().id,
            )
        )
        db.session.commit()
        return dashboard_redirect()

    @app.route("/formateur/remove/<kind>/<int:identity>", methods=["POST"])
    @access("formateur")
    def remove_record(kind, identity):
        choices = {
            "alert": (Alerte, "alerte"),
            "progress": (Progress, "livret"),
            "equipment": (Equipment, "materiel"),
            "transaction": (Transaction, "tresorerie"),
        }
        if kind not in choices:
            abort(404)
        model, module = choices[kind]
        if not getattr(active_section(), "module_" + module):
            abort(403)
        db.session.delete(scoped(model, identity))
        db.session.commit()
        return dashboard_redirect()

    def csv_response(rows, filename):
        output = StringIO()
        writer = csv.writer(output, delimiter=";")
        for row in rows:
            writer.writerow(
                [
                    "'" + value
                    if isinstance(value, str)
                    and value.lstrip().startswith(("=", "+", "-", "@"))
                    else value
                    for value in row
                ]
            )
        return Response(
            "\ufeff" + output.getvalue(),
            mimetype="text/csv",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "Cache-Control": "no-store",
            },
        )

    @app.route("/formateur/export-stats")
    @access("formateur", "stats")
    def export_stats():
        sec = active_section()
        rows = [["Prénom", "Nom", "Niveau", "Présent", "Absent", "En attente"]]
        for user in (
            User.query.filter_by(section_id=sec.id, role="jsp").order_by(User.nom).all()
        ):
            responses = (
                [r for r in user.event_responses if r.event.event_type == "seance"]
                if sec.module_seances
                else []
            )
            rows.append(
                [
                    user.prenom,
                    user.nom,
                    user.level,
                    *[
                        sum(r.status == status for r in responses)
                        for status in ["present", "absent", "en_attente"]
                    ],
                ]
            )
        return csv_response(rows, "statistiques.csv")

    @app.route("/formateur/export-treasury")
    @access("formateur", "tresorerie")
    def export_treasury():
        sec = active_section()
        rows = [["Date", "Libellé", "Montant (EUR)"]]
        rows.extend(
            [item.date.isoformat(), item.title, item.amount]
            for item in Transaction.query.filter_by(section_id=sec.id)
            .order_by(Transaction.date)
            .all()
        )
        return csv_response(rows, "tresorerie.csv")

    @app.route("/health")
    def health():
        try:
            db.session.execute(text("SELECT id FROM section LIMIT 1"))
            return {"status": "ok"}
        except Exception:
            db.session.rollback()
            return {"status": "unavailable"}, 503


app = create_app()
if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", "5000")), debug=False)
