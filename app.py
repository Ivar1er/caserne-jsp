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
from models import Course, Evaluation, Event, EventResponse, User, db
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get(
    'SECRET_KEY', 'cle_secrete_par_defaut_a_changer'
)

# Gestion de la base de données (compatible SQLite local & PostgreSQL sur Render)
db_url = os.environ.get('DATABASE_URL', 'sqlite:///caserne.db')
if db_url and db_url.startswith('postgres://'):
  db_url = db_url.replace('postgres://', 'postgresql://', 1)
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


# Initialisation automatique de la base de données et du compte admin au démarrage (requis pour Render)
with app.app_context():
  db.create_all()
  if not User.query.filter_by(role='admin').first():
    admin_user = User(
        username='admin',
        password_hash=generate_password_hash('Admin2026!'),
        role='admin',
        prenom='Nicolas',
        nom='Admin',
        email='admin@caserne.fr',
        first_login=False,
    )
    db.session.add(admin_user)
    db.session.commit()


# Sécurité: Forcer le changement de mot de passe à la première connexion
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


# --- AUTHENTIFICATION ---
@app.route('/login', methods=['GET', 'POST'])
def login():
  if request.method == 'POST':
    username = request.form.get('username')
    password = request.form.get('password')
    user = User.query.filter_by(username=username).first()
    if user and check_password_hash(user.password_hash, password):
      login_user(user)
      return redirect(url_for('index'))
    flash('Identifiant ou mot de passe incorrect.', 'danger')
  return render_template('login.html')


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
          f'Un mot de passe provisoire a été envoyé à {email}. (Mode test,'
          f' provisoire : {temp_pw})',
          'info',
      )
      return redirect(url_for('login'))
    flash('Aucun compte associé à cet e-mail.', 'danger')
  return render_template('forgot_password.html')


# --- ESPACE FORMATEUR / ADMIN ---
@app.route('/formateur')
@login_required
def dashboard_formateur():
  if current_user.role not in ['admin', 'formateur']:
    return redirect(url_for('index'))

  jsps = User.query.filter_by(role='jsp').all()
  courses = Course.query.order_by(Course.upload_date.desc()).all()
  events = Event.query.order_by(Event.date_time.asc()).all()
  return render_template(
      'dashboard_formateur.html', jsps=jsps, courses=courses, events=events
  )


@app.route('/admin/users', methods=['GET', 'POST'])
@login_required
def manage_users():
  if current_user.role != 'admin':
    flash("Accès réservé à l'administrateur.", 'danger')
    return redirect(url_for('index'))

  if request.method == 'POST':
    username = request.form.get('username')
    role = request.form.get('role')
    nom = request.form.get('nom', '')
    prenom = request.form.get('prenom', '')
    temp_pw = 'JSPinit2026'

    if User.query.filter_by(username=username).first():
      flash("Ce nom d'utilisateur existe déjà.", 'danger')
    else:
      new_user = User(
          username=username,
          password_hash=generate_password_hash(temp_pw),
          role=role,
          nom=nom,
          prenom=prenom,
          first_login=True,
      )
      db.session.add(new_user)
      db.session.commit()

      if role == 'jsp':
        events = Event.query.all()
        for ev in events:
          db.session.add(EventResponse(event_id=ev.id, jsp_id=new_user.id))
        db.session.commit()

      flash(
          f'Compte {username} créé avec succès (Mot de passe provisoire :'
          f' {temp_pw}).',
          'success',
      )
    return redirect(url_for('manage_users'))

  users = User.query.all()
  return render_template('manage_users.html', users=users)


@app.route('/formateur/upload-course', methods=['POST'])
@login_required
def upload_course():
  if current_user.role not in ['admin', 'formateur']:
    return redirect(url_for('index'))
  title = request.form.get('title')
  file = request.files.get('file')
  if file and title:
    filename = secure_filename(file.filename)
    file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
    new_course = Course(
        title=title,
        filename=filename,
        uploaded_by=f'{current_user.prenom} {current_user.nom}',
    )
    db.session.add(new_course)
    db.session.commit()
    flash('Cours ajouté avec succès.', 'success')
  return redirect(url_for('dashboard_formateur'))


@app.route('/formateur/upload-eval/<int:jsp_id>', methods=['POST'])
@login_required
def upload_eval(jsp_id):
  if current_user.role not in ['admin', 'formateur']:
    return redirect(url_for('index'))
  title = request.form.get('title')
  file = request.files.get('file')
  if file and title:
    filename = secure_filename(file.filename)
    file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
    new_eval = Evaluation(
        jsp_id=jsp_id,
        title=title,
        filename=filename,
        uploaded_by=f'{current_user.prenom} {current_user.nom}',
    )
    db.session.add(new_eval)
    db.session.commit()
    flash('Évaluation déposée avec succès.', 'success')
  return redirect(url_for('dashboard_formateur'))


@app.route('/formateur/create-event', methods=['POST'])
@login_required
def create_event():
  if current_user.role not in ['admin', 'formateur']:
    return redirect(url_for('index'))
  title = request.form.get('title')
  description = request.form.get('description')
  date_str = request.form.get('date_time')
  location = request.form.get('location')

  if title and date_str:
    date_time = datetime.strptime(date_str, '%Y-%m-%dT%H:%M')
    new_event = Event(
        title=title,
        description=description,
    )
    new_event = Event(
        title=title,
        description=description,
        date_time=date_time,
        location=location,
        created_by=f'{current_user.prenom} {current_user.nom}',
    )
    db.session.add(new_event)
    db.session.commit()

    jsps = User.query.filter_by(role='jsp').all()
    for jsp in jsps:
      db.session.add(EventResponse(event_id=new_event.id, jsp_id=jsp.id))
    db.session.commit()

    flash('Événement / Séance créé avec succès.', 'success')
  return redirect(url_for('dashboard_formateur'))


# --- ESPACE JSP ---
@app.route('/jsp')
@login_required
def dashboard_jsp():
  if current_user.role != 'jsp':
    return redirect(url_for('index'))
  courses = Course.query.order_by(Course.upload_date.desc()).all()
  evaluations = Evaluation.query.filter_by(jsp_id=current_user.id).all()
  events = Event.query.order_by(Event.date_time.asc()).all()
  responses = {r.event_id: r.status for r in current_user.responses}
  return render_template(
      'dashboard_jsp.html',
      courses=courses,
      evaluations=evaluations,
      events=events,
      responses=responses,
  )


@app.route('/jsp/respond-event/<int:event_id>', methods=['POST'])
@login_required
def respond_event(event_id):
  if current_user.role != 'jsp':
    return redirect(url_for('index'))
  status = request.form.get('status')
  response_entry = EventResponse.query.filter_by(
      event_id=event_id, jsp_id=current_user.id
  ).first()
  if response_entry:
    response_entry.status = status
    db.session.commit()
    flash('Réponse enregistrée.', 'success')
  return redirect(url_for('dashboard_jsp'))


@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
  if request.method == 'POST':
    current_user.nom = request.form.get('nom')
    current_user.prenom = request.form.get('prenom')
    current_user.email = request.form.get('email')
    db.session.commit()
    flash('Informations mises à jour.', 'success')
    return redirect(url_for('index'))
  return render_template('profile.html')


if __name__ == '__main__':
  app.run(debug=True)