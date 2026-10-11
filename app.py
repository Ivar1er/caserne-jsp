from datetime import datetime
import os
from flask import (
    Flask,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import (
    LoginManager,
    current_user,
    login_required,
    login_user,
    logout_user,
)
from models import (
    Alerte,
    Course,
    Evaluation,
    Event,
    EventResponse,
    Grade,
    JspDocument,
    Section,
    User,
    db,
)
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get(
    'SECRET_KEY', 'cle_secrete_par_defaut_a_changer'
)

db_url = os.environ.get('DATABASE_URL', 'sqlite:///caserne.db')
if db_url:
  if db_url.startswith('postgres://'):
    db_url = db_url.replace('postgres://', 'postgresql+pg8000://', 1)
  elif db_url.startswith('postgresql://'):
    db_url = db_url.replace('postgresql://', 'postgresql+pg8000://', 1)
app.config['SQLALCHEMY_DATABASE_URI'] = db_url

app.config['UPLOAD_FOLDER'] = 'static/uploads'
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

db.init_app(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'


@login_manager.user_loader
def load_user(user_id):
  return User.query.get(int(user_id))


# --- GESTIONNAIRES D'ERREURS POUR ÉVITER LES PAGES BLANCHES 500 ---
@app.errorhandler(500)
def internal_error(error):
  db.session.rollback()
  flash(
      'Une erreur interne est survenue. L’action a été annulée en toute'
      ' sécurité.',
      'danger',
  )
  if current_user.is_authenticated:
    if current_user.role == 'admin':
      return redirect(url_for('manage_sections'))
    elif current_user.role == 'formateur':
      return redirect(url_for('dashboard_formateur'))
    else:
      return redirect(url_for('dashboard_jsp'))
  return redirect(url_for('login'))


with app.app_context():
  db.create_all()

  default_sec = Section.query.first()
  if not default_sec:
    default_sec = Section(nom='Section St Germain / Château-Renard')
    db.session.add(default_sec)
    db.session.commit()

  if not User.query.filter_by(role='admin').first():
    admin_user = User(
        username='admin',
        password_hash=generate_password_hash('Admin2026!'),
        role='admin',
        prenom='Super',
        nom='Admin',
        email='admin@saas.fr',
        section_id=None,
        first_login=False,
    )
    db.session.add(admin_user)
    db.session.commit()


@app.before_request
def check_first_login():
  if current_user.is_authenticated and current_user.first_login:
    allowed_endpoints = ['change_password', 'logout', 'static', 'profile']
    if request.endpoint and request.endpoint not in allowed_endpoints:
      flash(
          'Veuillez modifier votre mot de passe provisoire et renseigner votre'
          ' email.',
          'warning',
      )
      return redirect(url_for('change_password'))


@app.route('/')
def index():
  if not current_user.is_authenticated:
    return redirect(url_for('login'))
  if current_user.role == 'admin':
    return redirect(url_for('manage_sections'))
  elif current_user.role == 'formateur':
    return redirect(url_for('dashboard_formateur'))
  else:
    return redirect(url_for('dashboard_jsp'))


@app.route('/login', methods=['GET', 'POST'])
def login():
  sections = Section.query.order_by(Section.nom).all()
  if request.method == 'POST':
    username = request.form.get('username', '').strip()
    password = request.form.get('password')
    sec_id = request.form.get('section_id')

    user = (
        User.query.filter(db.func.lower(User.username) == username.lower())
        .first()
    )

    if user and check_password_hash(user.password_hash, password):
      if user.role == 'admin':
        login_user(user)
        return redirect(url_for('index'))
      elif sec_id and str(user.section_id) == str(sec_id):
        login_user(user)
        return redirect(url_for('index'))
      else:
        flash(
            f'Erreur de section : Ce compte est rattaché à la section ID'
            f' {user.section_id}.',
            'danger',
        )
    else:
      flash(
          'Identifiant ou mot de passe incorrect (ou compte introuvable).',
          'danger',
      )
  return render_template('login.html', sections=sections)


@app.route('/logout')
@login_required
def logout():
  logout_user()
  return redirect(url_for('login'))


@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
  if request.method == 'POST':
    current_user.prenom = request.form.get('prenom', current_user.prenom)
    current_user.nom = request.form.get('nom', current_user.nom)
    current_user.email = request.form.get('email', current_user.email)
    db.session.commit()
    flash('Profil mis à jour avec succès.', 'success')
    return redirect(url_for('profile'))
  return render_template('profile.html')


@app.route('/change-password', methods=['GET', 'POST'])
@login_required
def change_password():
  if request.method == 'POST':
    new_password = request.form.get('new_password')
    email = request.form.get('email')

    if not new_password or len(new_password) < 6:
      flash('Le mot de passe doit faire au moins 6 caractères.', 'danger')
      return redirect(url_for('change_password'))

    current_user.password_hash = generate_password_hash(new_password)
    if email:
      current_user.email = email
    current_user.first_login = False
    db.session.commit()
    flash('Mot de passe mis à jour avec succès !', 'success')
    return redirect(url_for('index'))
  return render_template('change_password.html')


@app.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
  if request.method == 'POST':
    email = request.form.get('email')
    user = User.query.filter_by(email=email).first()
    if user:
      temp_pw = 'JSP2026!'
      user.password_hash = generate_password_hash(temp_pw)
      user.first_login = True
      db.session.commit()
      flash(f'Un mot de passe provisoire ({temp_pw}) vous a été attribué.', 'info')
      return redirect(url_for('login'))
    flash('Aucun compte associé à cet e-mail.', 'danger')
  return render_template('forgot_password.html')


# --- SUPER-ADMIN GLOBAL ---
@app.route('/admin/sections', methods=['GET', 'POST'])
@login_required
def manage_sections():
  if current_user.role != 'admin':
    flash('Accès réservé au Super-Administrateur.', 'danger')
    return redirect(url_for('index'))

  if request.method == 'POST':
    action = request.form.get('action')

    if action == 'create_section':
      nom = request.form.get('nom')
      if nom and not Section.query.filter_by(nom=nom).first():
        new_sec = Section(nom=nom)
        db.session.add(new_sec)
        db.session.commit()
        flash(f'Section "{nom}" créée avec succès.', 'success')

    elif action == 'toggle_modules':
      sec_id = request.form.get('section_id')
      sec = Section.query.get_or_404(sec_id)
      sec.module_calendrier = 'module_calendrier' in request.form
      sec.module_seances = 'module_seances' in request.form
      sec.module_fiches = 'module_fiches' in request.form
      sec.module_evaluations = 'module_evaluations' in request.form
      sec.module_cours = 'module_cours' in request.form
      sec.module_livret = 'module_livret' in request.form
      sec.module_materiel = 'module_materiel' in request.form
      sec.module_stats = 'module_stats' in request.form
      sec.module_alerte = 'module_alerte' in request.form
      sec.module_tresorerie = 'module_tresorerie' in request.form
      db.session.commit()
      flash(f'Modules de la section "{sec.nom}" mis à jour.', 'success')

    return redirect(url_for('manage_sections'))

  sections = Section.query.order_by(Section.nom).all()
  users = User.query.order_by(User.nom).all()
  return render_template('manage_sections.html', sections=sections, users=users)


@app.route('/admin/create-user', methods=['POST'])
@login_required
def admin_create_user():
  if current_user.role != 'admin':
    return redirect(url_for('index'))

  username = request.form.get('username')
  role = request.form.get('role')
  level = request.form.get('level', 'JSP 1') if role == 'jsp' else 'N/A'
  nom = request.form.get('nom', '')
  prenom = request.form.get('prenom', '')

  section_id_raw = request.form.get('section_id')
  section_id = int(section_id_raw) if section_id_raw else None

  temp_pw = 'JSPinit2026'

  if User.query.filter_by(username=username).first():
    flash("Ce nom d'utilisateur existe déjà.", 'danger')
  else:
    new_user = User(
        username=username,
        password_hash=generate_password_hash(temp_pw),
        role=role,
        level=level,
        nom=nom,
        prenom=prenom,
        section_id=section_id,
        first_login=True,
    )
    db.session.add(new_user)
    db.session.commit()

    if section_id:
      events = Event.query.filter_by(section_id=section_id).all()
      for ev in events:
        db.session.add(EventResponse(event_id=ev.id, jsp_id=new_user.id))
      db.session.commit()

    flash(f'Compte {username} créé avec succès.', 'success')
  return redirect(url_for('manage_sections'))


@app.route('/admin/delete-user/<int:user_id>', methods=['POST'])
@login_required
def delete_user(user_id):
  if current_user.role != 'admin':
    return redirect(url_for('index'))
  user = User.query.get_or_404(user_id)
  if user.id != current_user.id:
    db.session.delete(user)
    db.session.commit()
    flash('Compte supprimé avec succès.', 'success')
  return redirect(url_for('manage_sections'))


@app.route('/admin/delete-section/<int:section_id>', methods=['POST'])
@login_required
def delete_section(section_id):
  if current_user.role != 'admin':
    return redirect(url_for('index'))
  sec = Section.query.get_or_404(section_id)

  User.query.filter_by(section_id=sec.id).delete()
  Event.query.filter_by(section_id=sec.id).delete()
  Course.query.filter_by(section_id=sec.id).delete()
  Evaluation.query.filter_by(section_id=sec.id).delete()
  Alerte.query.filter_by(section_id=sec.id).delete()

  db.session.delete(sec)
  db.session.commit()
  flash(f'Section "{sec.nom}" supprimée.', 'success')
  return redirect(url_for('manage_sections'))


# --- ESPACE FORMATEUR (SÉCURISÉ) ---
@app.route('/formateur')
@login_required
def dashboard_formateur():
  if current_user.role not in ['admin', 'formateur']:
    return redirect(url_for('index'))
  if not current_user.section:
    flash("Votre compte n'est rattaché à aucune section.", 'danger')
    return redirect(url_for('logout'))

  sec = current_user.section
  jsps = (
      User.query.filter_by(role='jsp', section_id=sec.id)
      .order_by(User.nom)
      .all()
  )
  formateurs = (
      User.query.filter(
          User.role.in_(['admin', 'formateur']), User.section_id == sec.id
      )
      .order_by(User.nom)
      .all()
  )

  # Filtrage sécurisé par section
  courses = (
      Course.query.filter_by(section_id=sec.id).all()
      if hasattr(Course, 'section_id')
      else []
  )
  evaluations = (
      Evaluation.query.filter_by(section_id=sec.id).all()
      if hasattr(Evaluation, 'section_id')
      else []
  )
  events = (
      Event.query.filter_by(section_id=sec.id)
      .order_by(Event.date_time.asc())
      .all()
  )
  alertes = (
      Alerte.query.filter_by(section_id=sec.id)
      .order_by(Alerte.date_posted.desc())
      .all()
  )

  return render_template(
      'dashboard_formateur.html',
      sec=sec,
      jsps=jsps,
      formateurs=formateurs,
      courses=courses,
      evaluations=evaluations,
      events=events,
      alertes=alertes,
  )


# --- ESPACE JSP (SÉCURISÉ) ---
@app.route('/jsp')
@login_required
def dashboard_jsp():
  if current_user.role != 'jsp':
    return redirect(url_for('index'))
  sec = current_user.section
  if not sec:
    flash("Aucune section associée à ce compte.", 'danger')
    return redirect(url_for('logout'))

  courses = (
      Course.query.filter_by(section_id=sec.id).all()
      if hasattr(Course, 'section_id')
      else []
  )
  evaluations = (
      Evaluation.query.filter_by(section_id=sec.id).all()
      if hasattr(Evaluation, 'section_id')
      else []
  )
  events = (
      Event.query.filter_by(section_id=sec.id)
      .order_by(Event.date_time.asc())
      .all()
  )
  alertes = (
      Alerte.query.filter_by(section_id=sec.id)
      .order_by(Alerte.date_posted.desc())
      .all()
  )
  grades = Grade.query.filter_by(jsp_id=current_user.id).all()
  responses = {r.event_id: r.status for r in current_user.event_responses}
  formateurs = User.query.filter(
      User.role.in_(['admin', 'formateur']), User.section_id == sec.id
  ).all()
  jsp_docs = JspDocument.query.filter_by(jsp_id=current_user.id).all()

  return render_template(
      'dashboard_jsp.html',
      sec=sec,
      courses=courses,
      evaluations=evaluations,
      events=events,
      alertes=alertes,
      grades=grades,
      responses=responses,
      formateurs=formateurs,
      jsp_docs=jsp_docs,
  )


if __name__ == '__main__':
  app.run(debug=True)