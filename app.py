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
    Course,
    Evaluation,
    Event,
    EventResponse,
    Grade,
    JspDocument,
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
  db.create_all()
  if not User.query.filter_by(role='admin').first():
    admin_user = User(
        username='admin',
        password_hash=generate_password_hash('Admin2026!'),
        role='admin',
        prenom='Nicolas',
        nom='Admin',
        email='admin@caserne.fr',
        centre='Section St Germain / Château-Renard',
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
  if request.method == 'POST':
    username = request.form.get('username')
    password = request.form.get('password')
    selected_centre = request.form.get('centre')

    user = User.query.filter_by(username=username).first()
    if (
        user
        and check_password_hash(user.password_hash, password)
        and user.centre == selected_centre
    ):
      login_user(user)
      return redirect(url_for('index'))
    flash(
        'Identifiant, mot de passe incorrect ou centre non correspondant.',
        'danger',
    )
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
          f'Un mot de passe provisoire a été envoyé à {email}. (Provisoire :'
          f' {temp_pw})',
          'info',
      )
      return redirect(url_for('login'))
    flash('Aucun compte associé à cet e-mail.', 'danger')
  return render_template('forgot_password.html')


@app.route('/formateur')
@login_required
def dashboard_formateur():
  if current_user.role not in ['admin', 'formateur']:
    return redirect(url_for('index'))
  # Filtrage strict par centre
  jsps = (
      User.query.filter_by(role='jsp', centre=current_user.centre)
      .order_by(User.nom)
      .all()
  )
  formateurs = (
      User.query.filter(
          User.role.in_(['admin', 'formateur']),
          User.centre == current_user.centre,
      )
      .order_by(User.nom)
      .all()
  )
  courses = (
      Course.query.filter_by(centre=current_user.centre)
      .order_by(Course.upload_date.desc())
      .all()
  )
  evaluations = (
      Evaluation.query.filter_by(centre=current_user.centre)
      .order_by(Evaluation.upload_date.desc())
      .all()
  )
  events = (
      Event.query.filter_by(centre=current_user.centre)
      .order_by(Event.date_time.asc())
      .all()
  )
  return render_template(
      'dashboard_formateur.html',
      jsps=jsps,
      formateurs=formateurs,
      courses=courses,
      evaluations=evaluations,
      events=events,
  )


@app.route('/admin/users', methods=['GET', 'POST'])
@login_required
def manage_users():
  if current_user.role != 'admin':
    flash("Accès réservé exclusivement à l'administrateur.", 'danger')
    return redirect(url_for('index'))

  if request.method == 'POST':
    username = request.form.get('username')
    role = request.form.get('role')
    level = (
        request.form.get('level', 'JSP 1') if role == 'jsp' else 'N/A'
    )
    nom = request.form.get('nom', '')
    prenom = request.form.get('prenom', '')
    centre = request.form.get(
        'centre', 'Section St Germain / Château-Renard'
    )
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
          centre=centre,
          first_login=True,
      )
      db.session.add(new_user)
      db.session.commit()

      events = Event.query.filter_by(centre=centre).all()
      for ev in events:
        db.session.add(EventResponse(event_id=ev.id, jsp_id=new_user.id))
      db.session.commit()

      flash(
          f'Compte {username} créé avec succès (Centre : {centre} | Rôle :'
          f' {role}).',
          'success',
      )
    return redirect(url_for('manage_users'))

  users = User.query.filter_by(centre=current_user.centre).all()
  return render_template('manage_users.html', users=users)


@app.route('/admin/delete-user/<int:user_id>', methods=['POST'])
@login_required
def delete_user(user_id):
  if current_user.role != 'admin':
    flash("Accès réservé exclusivement à l'administrateur.", 'danger')
    return redirect(url_for('index'))

  user_to_delete = User.query.get_or_404(user_id)
  if user_to_delete.id == current_user.id:
    flash('Vous ne pouvez pas supprimer votre propre compte.', 'danger')
    return redirect(url_for('manage_users'))

  db.session.delete(user_to_delete)
  db.session.commit()
  flash('Compte supprimé avec succès.', 'success')
  return redirect(url_for('manage_users'))


@app.route('/formateur/update-level/<int:jsp_id>', methods=['POST'])
@login_required
def update_jsp_level(jsp_id):
  if current_user.role not in ['admin', 'formateur']:
    return redirect(url_for('index'))
  jsp = User.query.get_or_404(jsp_id)
  if jsp.role == 'jsp' and jsp.centre == current_user.centre:
    new_level = request.form.get('level')
    if new_level in ['JSP 1', 'JSP 2', 'JSP 3', 'JSP 4']:
      jsp.level = new_level
      db.session.commit()
      flash(
          f'Niveau de {jsp.prenom} {jsp.nom} mis à jour ({new_level}). Ses notes'
          ' antérieures sont archivées.',
          'success',
      )
  return redirect(url_for('dashboard_formateur'))


@app.route('/formateur/update-jsp-info/<int:jsp_id>', methods=['POST'])
@login_required
def update_jsp_info(jsp_id):
  if current_user.role not in ['admin', 'formateur']:
    return redirect(url_for('index'))
  jsp = User.query.get_or_404(jsp_id)
  if jsp.centre == current_user.centre:
    jsp.email = request.form.get('email')
    jsp.adresse = request.form.get('adresse')
    jsp.centre = request.form.get('centre')
    date_n = request.form.get('date_naissance')
    if date_n:
      try:
        jsp.date_naissance = datetime.strptime(date_n, '%Y-%m-%d').date()
      except ValueError:
        pass
    db.session.commit()
    flash('Fiche mise à jour avec succès.', 'success')
  return redirect(url_for('dashboard_formateur'))


@app.route('/formateur/add-grade/<int:jsp_id>', methods=['POST'])
@login_required
def add_grade(jsp_id):
  if current_user.role not in ['admin', 'formateur']:
    return redirect(url_for('index'))
  jsp = User.query.get_or_404(jsp_id)
  title = request.form.get('title')
  score_str = request.form.get('score')
  if title and score_str:
    try:
      score = float(score_str)
      # Enregistre avec le niveau actuel du JSP pour archivage automatique par année
      new_grade = Grade(
          jsp_id=jsp_id,
          title=title,
          score=score,
          level_attained=jsp.level,
      )
      db.session.add(new_grade)
      db.session.commit()
      flash('Note enregistrée avec succès.', 'success')
    except ValueError:
      flash('Format de note invalide.', 'danger')
  return redirect(url_for('dashboard_formateur'))


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
        centre=current_user.centre,
    )
    db.session.add(new_event)
    db.session.commit()

    users = User.query.filter(
        User.centre == current_user.centre,
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
    flash('Événement ou séance publié avec succès.', 'success')
  return redirect(url_for('dashboard_formateur'))


@app.route('/formateur/edit-event/<int:event_id>', methods=['POST'])
@login_required
def edit_event(event_id):
  if current_user.role not in ['admin', 'formateur']:
    return redirect(url_for('index'))
  event = Event.query.get_or_404(event_id)
  if event.centre == current_user.centre:
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
  if event.centre == current_user.centre:
    db.session.delete(event)
    db.session.commit()
    flash('Événement supprimé avec succès.', 'success')
  return redirect(url_for('dashboard_formateur'))


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
        centre=current_user.centre,
    )
    db.session.add(new_course)
    db.session.commit()
    flash('Cours ajouté avec succès.', 'success')
  return redirect(url_for('dashboard_formateur'))


@app.route('/formateur/upload-eval', methods=['POST'])
@login_required
def upload_eval():
  if current_user.role not in ['admin', 'formateur']:
    return redirect(url_for('index'))
  title = request.form.get('title')
  file = request.files.get('file')
  if file and title:
    filename = secure_filename(file.filename)
    file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
    new_eval = Evaluation(
        title=title,
        filename=filename,
        uploaded_by=f'{current_user.prenom} {current_user.nom}',
        centre=current_user.centre,
    )
    db.session.add(new_eval)
    db.session.commit()
    flash('Évaluation publiée avec succès.', 'success')
  return redirect(url_for('dashboard_formateur'))


@app.route('/jsp')
@login_required
def dashboard_jsp():
  if current_user.role != 'jsp':
    return redirect(url_for('index'))
  courses = (
      Course.query.filter_by(centre=current_user.centre)
      .order_by(Course.upload_date.desc())
      .all()
  )
  evaluations = (
      Evaluation.query.filter_by(centre=current_user.centre)
      .order_by(Evaluation.upload_date.desc())
      .all()
  )
  events = (
      Event.query.filter_by(centre=current_user.centre)
      .order_by(Event.date_time.asc())
      .all()
  )
  grades = Grade.query.filter_by(jsp_id=current_user.id).all()
  responses = {r.event_id: r.status for r in current_user.event_responses}
  formateurs = (
      User.query.filter(
          User.role.in_(['admin', 'formateur']),
          User.centre == current_user.centre,
      )
      .all()
  )
  jsp_docs = JspDocument.query.filter_by(jsp_id=current_user.id).all()

  return render_template(
      'dashboard_jsp.html',
      courses=courses,
      evaluations=evaluations,
      events=events,
      grades=grades,
      responses=responses,
      formateurs=formateurs,
      jsp_docs=jsp_docs,
  )


@app.route('/jsp/respond-event/<int:event_id>', methods=['POST'])
@login_required
def respond_event(event_id):
  status = request.form.get('status')
  response_entry = EventResponse.query.filter_by(
      event_id=event_id, jsp_id=current_user.id
  ).first()
  if response_entry:
    response_entry.status = status
    db.session.commit()
    flash('Votre réponse a été enregistrée.', 'success')
  if current_user.role == 'jsp':
    return redirect(url_for('dashboard_jsp'))
  else:
    return redirect(url_for('dashboard_formateur'))


@app.route('/jsp/upload-doc', methods=['POST'])
@login_required
def jsp_upload_doc():
  if current_user.role != 'jsp':
    return redirect(url_for('index'))
  title = request.form.get('title')
  formateur_id = request.form.get('formateur_id')
  file = request.files.get('file')

  if file and title:
    filename = secure_filename(file.filename)
    file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
    new_doc = JspDocument(
        jsp_id=current_user.id,
        formateur_id=int(formateur_id) if formateur_id else None,
        title=title,
        filename=filename,
        level_attained=current_user.level,
    )
    db.session.add(new_doc)
    db.session.commit()
    flash('Document transmis avec succès.', 'success')
  return redirect(url_for('dashboard_jsp'))


@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
  if request.method == 'POST':
    current_user.nom = request.form.get('nom')
    current_user.prenom = request.form.get('prenom')
    current_user.email = request.form.get('email')
    current_user.centre = request.form.get('centre')
    db.session.commit()
    flash('Informations mises à jour.', 'success')
    return redirect(url_for('index'))
  return render_template('profile.html')


if __name__ == '__main__':
  app.run(debug=True)