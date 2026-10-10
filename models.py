from datetime import datetime
from flask_login import UserMixin
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


class User(UserMixin, db.Model):
  id = db.Column(db.Integer, primary_key=True)
  username = db.Column(db.String(80), unique=True, nullable=False)
  password_hash = db.Column(db.String(200), nullable=False)
  role = db.Column(db.String(20), nullable=False)  # 'admin', 'formateur', 'jsp'
  level = db.Column(db.String(10), default='JSP 1')  # 'JSP 1' à 'JSP 4'
  nom = db.Column(db.String(80), default='')
  prenom = db.Column(db.String(80), default='')
  email = db.Column(db.String(120), unique=True, nullable=True)
  first_login = db.Column(db.Boolean, default=True)


class Event(db.Model):
  id = db.Column(db.Integer, primary_key=True)
  title = db.Column(db.String(150), nullable=False)
  description = db.Column(db.Text, nullable=True)
  date_time = db.Column(db.DateTime, nullable=False)
  end_time = db.Column(db.DateTime, nullable=True)
  location = db.Column(db.String(150), nullable=True)
  created_by = db.Column(db.String(80), nullable=False)
  event_type = db.Column(
      db.String(20), default='seance'
  )  # 'calendrier' ou 'seance'
  target_level = db.Column(
      db.String(20), default='Tous'
  )  # 'Tous', 'JSP 1', 'JSP 2', 'JSP 3', 'JSP 4'


class EventResponse(db.Model):
  id = db.Column(db.Integer, primary_key=True)
  event_id = db.Column(db.Integer, db.ForeignKey('event.id'), nullable=False)
  jsp_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
  status = db.Column(db.String(20), default='en_attente')

  event = db.relationship(
      'Event', backref=db.backref('responses', cascade='all, delete-orphan')
  )
  jsp = db.relationship(
      'User', backref=db.backref('event_responses', lazy=True)
  )


class Grade(db.Model):
  id = db.Column(db.Integer, primary_key=True)
  jsp_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
  title = db.Column(db.String(150), nullable=False)
  score = db.Column(db.Float, nullable=False)
  date = db.Column(db.DateTime, default=datetime.utcnow)
  jsp = db.relationship(
      'User', backref=db.backref('grades', cascade='all, delete-orphan')
  )


class Course(db.Model):
  id = db.Column(db.Integer, primary_key=True)
  title = db.Column(db.String(150), nullable=False)
  filename = db.Column(db.String(200), nullable=False)
  upload_date = db.Column(db.DateTime, default=datetime.utcnow)
  uploaded_by = db.Column(db.String(80), nullable=False)


class Evaluation(db.Model):
  id = db.Column(db.Integer, primary_key=True)
  title = db.Column(db.String(150), nullable=False)
  filename = db.Column(db.String(200), nullable=False)
  upload_date = db.Column(db.DateTime, default=datetime.utcnow)
  uploaded_by = db.Column(db.String(80), nullable=False)


class JspDocument(db.Model):
  id = db.Column(db.Integer, primary_key=True)
  jsp_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
  formateur_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
  title = db.Column(db.String(150), nullable=False)
  filename = db.Column(db.String(200), nullable=False)
  upload_date = db.Column(db.DateTime, default=datetime.utcnow)
  jsp = db.relationship(
      'User', foreign_keys=[jsp_id], backref=db.backref('jsp_docs', lazy=True)
  )
  formateur = db.relationship(
      'User',
      foreign_keys=[formateur_id],
      backref=db.backref('assigned_docs', lazy=True),
  )