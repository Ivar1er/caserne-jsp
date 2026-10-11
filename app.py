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
    Competence,
    Cotisation,
    Course,
    EpiItem,
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


with app.app_context():
  db.drop_all()
  db.create_all()

  # Section par défaut de test
  default_sec = Section.query.filter_by(
      nom='Section St Germain / Château-Renard'
  ).first()
  if not default_sec:
    default_sec = Section(nom='Section St Germain / Château-Renard')
    db.session.add(default_sec)
    db.session.commit()

  if not User.query.filter_by(role='admin').first():
    admin_user = User(
        username='admin',
        password_hash=generate_password_hash('Admin2026!'),
        role='admin',
        prenom='Nicolas',
        nom='Admin',
        email='admin@caserne.fr',
        section_id=default_sec.id,
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
  if current_user.role in ['admin', 'formateur']:
    return redirect(url_for('dashboard_formateur'))
  else:
    return redirect(url_for('dashboard_jsp'))


@app.route('/login', methods=['GET', 'POST'])
def login():
  sections = Section.query.order_by(Section.nom).all()
  if request.method == 'POST':
    username = request.form.get('username')
    password = request.form.get('password')
    sec_id = request.form.get('section_id')

    user = User.query.filter_by(username=username).first()
    if user and check_password_hash(user.password_hash, password):
      if user.role == 'admin' or str(user.section_id) == str(sec_id):
        if user.role == 'admin' and sec_id:
          user.section_id = int(sec_id)
          db.session.commit()
        login_user(user)
        return redirect(url_for('index'))

    flash(
        'Identifiant, mot de passe incorrect ou section non correspondante.',
        'danger',
    )
  return render_template('login.html', sections=sections)


@app.route('/logout')
@login_required
def logout():
  logout_user()
  return redirect(url_for('login'))


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
    flash('Mot de passe mis à jour avec succès.', 'success')
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
      flash(
          f'Un mot de passe provisoire a été envoyé à {email}. (Provisoire :'
          f' {temp_pw})',
          'info',
      )
      return redirect(url_for('login'))
    flash('Aucun compte associé à cet e-mail.', 'danger')
  return render_template('forgot_password.html')


# --- SUPER ADMIN : GESTION DES SECTIONS & MODULES ---
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
  section_id = request.form.get('section_id')
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


# --- ESPACE FORMATEUR & ADMIN ---
@app.route('/formateur')
@login_required
def dashboard_formateur():
  if current_user.role not in ['admin', 'formateur']:
    return redirect(url_for('index'))
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
  courses = (
      Course.query.filter_by(section_id=sec.id)
      .order_by(Course.upload_date.desc())
      .all()
  )
  evaluations = (
      Evaluation.query.filter_by(section_id=sec.id)
      .order_by(Evaluation.upload_date.desc())
      .all()
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


@app.route('/formateur/create-event', methods=['POST'])
@login_required
def create_event():
  if current_user.role not in ['admin', 'formateur']:
    return redirect(url_for('index'))
  title = request.form.get('title')
  description = request.form.get('description')
  date_str = request.form.get('date_time')
  end_str = request.form.get('end_time')
  location = request.form.get('location')
  event_type = request.form.get('event_type', 'seance')
  target_level = request.form.get('target_level', 'Tous')

  if title and date_str:
    date_time = datetime.strptime(date_str, '%Y-%m-%dT%H:%M')
    end_time = datetime.strptime(end_str, '%Y-%m-%dT%H:%M') if end_str else None
    new_event = Event(
        title=title,
        description=description,
        date_time=date_time,
        end_time=end_time,
        location=location,
        created_by=f'{current_user.prenom} {current_user.nom}',
        event_type=event_type,
        target_level=target_level,
        section_id=current_user.section_id,
    )
    db.session.add(new_event)
    db.session.commit()

    users = User.query.filter(
        User.section_id == current_user.section_id,
        User.role.in_(['jsp', 'formateur']),
    ).all()
    for u in users:
      if (
          u.role == 'formateur'
          or target_level == 'Tous'
          or u.level == target_level
      ):
        db.session.add(EventResponse(event_id=new_event.id, jsp_id=u.id))
    db.session.commit()
    flash('Événement ou séance publié.', 'success')
  return redirect(url_for('dashboard_formateur'))


@app.route('/formateur/edit-event/<int:event_id>', methods=['POST'])
@login_required
def edit_event(event_id):
  if current_user.role not in ['admin', 'formateur']:
    return redirect(url_for('index'))
  event = Event.query.get_or_404(event_id)
  if event.section_id == current_user.section_id:
    event.title = request.form.get('title')
    event.description = request.form.get('description')
    date_str = request.form.get('date_time')
    end_str = request.form.get('end_time')
    event.location = request.form.get('location')
    event.target_level = request.form.get('target_level', event.target_level)

    if date_str:
      event.date_time = datetime.strptime(date_str, '%Y-%m-%dT%H:%M')
    if end_str:
      event.end_time = datetime.strptime(end_str, '%Y-%m-%dT%H:%M')
    else:
      event.end_time = None

    db.session.commit()
    flash('Événement mis à jour avec succès.', 'success')
  return redirect(url_for('dashboard_formateur'))


@app.route('/formateur/delete-event/<int:event_id>', methods=['POST'])
@login_required
def delete_event(event_id):
  if current_user.role not in ['admin', 'formateur']:
    return redirect(url_for('index'))
  event = Event.query.get_or_404(event_id)
  if event.section_id == current_user.section_id:
    db.session.delete(event)
    db.session.commit()
    flash('Événement/Séance supprimé avec succès.', 'success')
  return redirect(url_for('dashboard_formateur'))


# --- ESPACE JSP ---
@app.route('/jsp')
@login_required
def dashboard_jsp():
  if current_user.role != 'jsp':
    return redirect(url_for('index'))
  sec = current_user.section
  courses = (
      Course.query.filter_by(section_id=sec.id)
      .order_by(Course.upload_date.desc())
      .all()
  )
  evaluations = (
      Evaluation.query.filter_by(section_id=sec.id)
      .order_by(Evaluation.upload_date.desc())
      .all()
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


@app.route('/jsp/respond-event/<int:event_id>', methods=['POST'])
@login_required
def respond_event(event_id):
  status = request.form.get('status')
  resp = EventResponse.query.filter_by(
      event_id=event_id, jsp_id=current_user.id
  ).first()
  if resp:
    resp.status = status
    db.session.commit()
    flash('Réponse enregistrée.', 'success')
  return redirect(
      url_for('dashboard_jsp')
      if current_user.role == 'jsp'
      else url_for('dashboard_formateur')
  )


if __name__ == '__main__':
  app.run(debug=True)