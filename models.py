from datetime import datetime
from flask_login import UserMixin
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


class User(UserMixin, db.Model):
  id = db.Column(db.Integer, primary_key=True)
  username = db.Column(db.String(80), unique=True, nullable=False)
  password_hash = db.Column(db.String(200), nullable=False)
  role = db.Column(db.String(20), nullable=False)
  nom = db.Column(db.String(80), default='')
  prenom = db.Column(db.String(80), default='')
  email = db.Column(db.String(120), unique=True, nullable=True)
  first_login = db.Column(db.Boolean, default=True)


class Course(db.Model):
  id = db.Column(db.Integer, primary_key=True)
  title = db.Column(db.String(150), nullable=False)
  filename = db.Column(db.String(200), nullable=False)
  upload_date = db.Column(db.DateTime, default=datetime.utcnow)
  uploaded_by = db.Column(db.String(80), nullable=False)


class Evaluation(db.Model):
  id = db.Column(db.Integer, primary_key=True)
  jsp_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
  title = db.Column(db.String(150), nullable=False)
  filename = db.Column(db.String(200), nullable=False)
  upload_date = db.Column(db.DateTime, default=datetime.utcnow)
  uploaded_by = db.Column(db.String(80), nullable=False)
  jsp = db.relationship('User', backref=db.backref('evaluations', lazy=True))


class Event(db.Model):
  id = db.Column(db.Integer, primary_key=True)
  title = db.Column(db.String(150), nullable=False)
  description = db.Column(db.Text, nullable=True)
  date_time = db.Column(db.DateTime, nullable=False)
  end_time = db.Column(db.DateTime, nullable=True)  # Heure de fin
  location = db.Column(db.String(150), nullable=True)
  created_by = db.Column(db.String(80), nullable=False)


class EventResponse(db.Model):
  id = db.Column(db.Integer, primary_key=True)
  event_id = db.Column(db.Integer, db.ForeignKey('event.id'), nullable=False)
  jsp_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
  status = db.Column(db.String(20), default='en_attente')
  event = db.relationship(
      'Event', backref=db.backref('responses', cascade='all, delete-orphan')
  )
  jsp = db.relationship('User', backref=db.backref('responses', lazy=True))