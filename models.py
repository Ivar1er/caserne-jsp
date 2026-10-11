"""Données des sections JSP. Suppressions via l'ORM pour conserver les cascades."""

from datetime import datetime, timezone
from flask_login import UserMixin
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Section(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nom = db.Column(db.String(100), unique=True, nullable=False)
    module_calendrier = db.Column(db.Boolean, default=True)
    module_seances = db.Column(db.Boolean, default=True)
    module_fiches = db.Column(db.Boolean, default=True)
    module_evaluations = db.Column(db.Boolean, default=True)
    module_cours = db.Column(db.Boolean, default=True)
    module_livret = db.Column(db.Boolean, default=True)
    module_materiel = db.Column(db.Boolean, default=True)
    module_stats = db.Column(db.Boolean, default=True)
    module_alerte = db.Column(db.Boolean, default=True)
    module_tresorerie = db.Column(db.Boolean, default=True)


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    role = db.Column(db.String(20), nullable=False)
    level = db.Column(db.String(10), default="JSP 1")
    nom = db.Column(db.String(80), default="")
    prenom = db.Column(db.String(80), default="")
    email = db.Column(db.String(120))
    date_naissance = db.Column(db.Date)
    adresse = db.Column(db.String(200))
    centre = db.Column(db.String(100), default="")
    auth_version = db.Column(db.Integer, nullable=False, default=1, server_default="1")
    section_id = db.Column(db.Integer, db.ForeignKey("section.id"))
    section = db.relationship(
        "Section", backref=db.backref("users", cascade="all, delete-orphan")
    )
    first_login = db.Column(db.Boolean, default=True)

    def get_id(self):
        return f"{self.id}:{self.auth_version}"


class Event(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(150), nullable=False)
    description = db.Column(db.Text)
    date_time = db.Column(db.DateTime, nullable=False)
    end_time = db.Column(db.DateTime)
    location = db.Column(db.String(150))
    created_by = db.Column(db.String(80), nullable=False)
    event_type = db.Column(db.String(20), default="seance")
    target_level = db.Column(db.String(20), default="Tous")
    section_id = db.Column(db.Integer, db.ForeignKey("section.id"), nullable=False)
    section = db.relationship(
        "Section", backref=db.backref("events", cascade="all, delete-orphan")
    )


class EventResponse(db.Model):
    __table_args__ = (
        db.UniqueConstraint("event_id", "jsp_id", name="uq_response_event_user"),
    )
    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey("event.id"), nullable=False)
    jsp_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    status = db.Column(db.String(20), default="en_attente")
    event = db.relationship(
        "Event", backref=db.backref("responses", cascade="all, delete-orphan")
    )
    jsp = db.relationship(
        "User", backref=db.backref("event_responses", cascade="all, delete-orphan")
    )


class Grade(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    jsp_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    title = db.Column(db.String(150), nullable=False)
    score = db.Column(db.Float, nullable=False)
    level_attained = db.Column(db.String(10), default="JSP 1")
    date = db.Column(db.DateTime, default=utcnow)
    jsp = db.relationship(
        "User", backref=db.backref("grades", cascade="all, delete-orphan")
    )


class Course(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(150), nullable=False)
    filename = db.Column(db.String(200), nullable=False)
    upload_date = db.Column(db.DateTime, default=utcnow)
    uploaded_by = db.Column(db.String(80), nullable=False)
    section_id = db.Column(db.Integer, db.ForeignKey("section.id"), nullable=False)
    section = db.relationship(
        "Section", backref=db.backref("courses", cascade="all, delete-orphan")
    )


class Evaluation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(150), nullable=False)
    filename = db.Column(db.String(200), nullable=False)
    upload_date = db.Column(db.DateTime, default=utcnow)
    uploaded_by = db.Column(db.String(80), nullable=False)
    section_id = db.Column(db.Integer, db.ForeignKey("section.id"), nullable=False)
    section = db.relationship(
        "Section", backref=db.backref("evaluations", cascade="all, delete-orphan")
    )


class JspDocument(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    jsp_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    formateur_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    title = db.Column(db.String(150), nullable=False)
    filename = db.Column(db.String(200), nullable=False)
    upload_date = db.Column(db.DateTime, default=utcnow)
    level_attained = db.Column(db.String(10), default="JSP 1")
    jsp = db.relationship(
        "User",
        foreign_keys=[jsp_id],
        backref=db.backref("jsp_docs", cascade="all, delete-orphan"),
    )
    formateur = db.relationship(
        "User", foreign_keys=[formateur_id], backref=db.backref("assigned_docs")
    )


class Alerte(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(150), nullable=False)
    content = db.Column(db.Text, nullable=False)
    date_posted = db.Column(db.DateTime, default=utcnow)
    section_id = db.Column(db.Integer, db.ForeignKey("section.id"), nullable=False)
    section = db.relationship(
        "Section", backref=db.backref("alertes", cascade="all, delete-orphan")
    )


class Progress(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    jsp_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    title = db.Column(db.String(150), nullable=False)
    level = db.Column(db.String(10), nullable=False)
    status = db.Column(db.String(20), nullable=False, default="en_cours")
    date = db.Column(db.DateTime, default=utcnow)
    jsp = db.relationship(
        "User", backref=db.backref("progress", cascade="all, delete-orphan")
    )


class Equipment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(150), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    condition = db.Column(db.String(20), nullable=False, default="bon")
    section_id = db.Column(db.Integer, db.ForeignKey("section.id"), nullable=False)
    section = db.relationship(
        "Section", backref=db.backref("equipment", cascade="all, delete-orphan")
    )


class Transaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(150), nullable=False)
    amount = db.Column(db.Numeric(12, 2), nullable=False)
    date = db.Column(db.Date, nullable=False)
    section_id = db.Column(db.Integer, db.ForeignKey("section.id"), nullable=False)
    section = db.relationship(
        "Section", backref=db.backref("transactions", cascade="all, delete-orphan")
    )


class RateAttempt(db.Model):
    """Compteurs partagés entre les workers (aucun mot de passe enregistré)."""

    key = db.Column(db.String(64), primary_key=True)
    count = db.Column(db.Integer, nullable=False, default=1)
    expires = db.Column(db.DateTime, nullable=False)
