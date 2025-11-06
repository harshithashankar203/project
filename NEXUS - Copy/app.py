from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_login import (
    LoginManager, login_user, logout_user, login_required,
    current_user, UserMixin
)
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
from config import Config
from flask_socketio import SocketIO, emit

# ------------------ APP SETUP ------------------
app = Flask(__name__)
app.config.from_object(Config)

db = SQLAlchemy(app)
socketio = SocketIO(app, cors_allowed_origins="*")
login_manager = LoginManager(app)
login_manager.login_view = 'login'

# ------------------ MANY-TO-MANY RELATION ------------------
board_collaborators = db.Table(
    'board_collaborators',
    db.Column('board_id', db.Integer, db.ForeignKey('board.id', ondelete="CASCADE"), primary_key=True),
    db.Column('user_id', db.Integer, db.ForeignKey('users.id', ondelete="CASCADE"), primary_key=True)
)

# ------------------ MODELS ------------------
class User(UserMixin, db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    date_created = db.Column(db.DateTime, default=datetime.utcnow)
    boards = db.relationship('Board', backref='owner', lazy=True, cascade="all, delete")

class Board(db.Model):
    __tablename__ = 'board'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    date_created = db.Column(db.DateTime, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete="CASCADE"), nullable=False)
    lists = db.relationship('List', backref='board', cascade="all, delete", lazy=True)
    collaborators = db.relationship('User', secondary=board_collaborators, backref='shared_boards', lazy='subquery')

class List(db.Model):
    __tablename__ = 'list'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    board_id = db.Column(db.Integer, db.ForeignKey('board.id', ondelete="CASCADE"), nullable=False)
    cards = db.relationship('Card', backref='list', cascade="all, delete", lazy=True, order_by="Card.position")

class Card(db.Model):
    __tablename__ = 'card'
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    position = db.Column(db.Integer, default=0)
    status = db.Column(db.String(20), default='Pending')
    date_created = db.Column(db.DateTime, default=datetime.utcnow)
    due_date = db.Column(db.DateTime, nullable=True)
    list_id = db.Column(db.Integer, db.ForeignKey('list.id', ondelete="CASCADE"), nullable=False)

class Comment(db.Model):
    __tablename__ = 'comment'
    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.Text, nullable=False)
    date_created = db.Column(db.DateTime, default=datetime.utcnow)
    card_id = db.Column(db.Integer, db.ForeignKey('card.id', ondelete="CASCADE"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete="CASCADE"), nullable=False)

    user = db.relationship('User', backref='comments')
    card = db.relationship('Card', backref='comments')

# ------------------ LOGIN MANAGEMENT ------------------
@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# ------------------ HELPERS ------------------
def safe_emit(event, data=None):
    try:
        if data is None:
            socketio.emit(event)
        else:
            socketio.emit(event, data)
    except Exception:
        pass

# ------------------ ROUTES ------------------
@app.route('/')
def home():
    return redirect(url_for('login'))

# ------------------ AUTH ------------------
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        uname = request.form['username'].strip()
        pwd = request.form['password'].strip()

        if not uname or not pwd:
            flash("⚠️ All fields are required!")
            return redirect(url_for('register'))

        if User.query.filter_by(username=uname).first():
            flash('⚠️ Username already exists!')
            return redirect(url_for('register'))

        hashed_pwd = generate_password_hash(pwd)
        new_user = User(username=uname, password=hashed_pwd)
        db.session.add(new_user)
        db.session.commit()
        flash('✅ Registration successful! Please login.')
        return redirect(url_for('login'))

    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        uname = request.form['username']
        pwd = request.form['password']
        user = User.query.filter_by(username=uname).first()

        if user and check_password_hash(user.password, pwd):
            login_user(user)
            flash("✅ Logged in successfully!")
            return redirect(url_for('dashboard'))
        else:
            flash('❌ Invalid username or password!')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('👋 You have been logged out.')
    return redirect(url_for('login'))

# ------------------ DASHBOARD ------------------
@app.route('/dashboard')
@login_required
def dashboard():
    search_query = request.args.get('search', '').strip().lower()
    owned = Board.query.filter_by(user_id=current_user.id).all()
    shared = current_user.shared_boards
    boards = owned + shared

    if search_query:
        boards = [b for b in boards if search_query in b.name.lower()]

    return render_template('dashboard.html', boards=boards, now=datetime.utcnow())

# ------------------ BOARD CRUD ------------------
@app.route('/create_board', methods=['POST'])
@login_required
def create_board():
    name = request.form['board_name'].strip()
    if not name:
        flash("⚠️ Board name cannot be empty.")
        return redirect(url_for('dashboard'))
    new_board = Board(name=name, user_id=current_user.id)
    db.session.add(new_board)
    db.session.commit()
    flash("✅ Board created successfully!")
    safe_emit('refresh_dashboard')
    return redirect(url_for('dashboard'))

@app.route('/update_board/<int:board_id>', methods=['POST'])
@login_required
def update_board(board_id):
    board = Board.query.get_or_404(board_id)
    if board.owner.id != current_user.id:
        flash("⚠️ Unauthorized action.")
        return redirect(url_for('dashboard'))

    board.name = request.form['board_name'].strip()
    db.session.commit()
    flash("✅ Board renamed successfully!")
    safe_emit('refresh_dashboard')
    return redirect(url_for('dashboard'))

@app.route('/delete_board/<int:board_id>', methods=['POST'])
@login_required
def delete_board(board_id):
    board = Board.query.get_or_404(board_id)
    if board.owner.id != current_user.id:
        flash("⚠️ Unauthorized action.")
        return redirect(url_for('dashboard'))
    db.session.delete(board)
    db.session.commit()
    flash("🗑️ Board deleted successfully!")
    safe_emit('refresh_dashboard')
    return redirect(url_for('dashboard'))

# ------------------ VIEW BOARD ------------------
@app.route('/board/<int:board_id>')
@login_required
def view_board(board_id):
    board = Board.query.get_or_404(board_id)
    if board.owner.id != current_user.id and current_user not in board.collaborators:
        flash("🚫 Access denied.")
        return redirect(url_for('dashboard'))

    lists = List.query.filter_by(board_id=board.id).all()
    now = datetime.utcnow()

    for lst in lists:
        for card in lst.cards:
            card.is_overdue = bool(card.due_date and card.due_date < now and card.status != "Done")

    return render_template('view_board.html', board=board, lists=lists, now=now)

# ------------------ LIST CRUD ------------------
@app.route('/add_list/<int:board_id>', methods=['POST'])
@login_required
def add_list(board_id):
    name = request.form['list_name'].strip()
    if not name:
        flash("⚠️ List name cannot be empty.")
        return redirect(url_for('view_board', board_id=board_id))

    new_list = List(name=name, board_id=board_id)
    db.session.add(new_list)
    db.session.commit()
    flash("🆕 List added successfully!")
    safe_emit('refresh_board', {'board_id': board_id})
    return redirect(url_for('view_board', board_id=board_id))

@app.route('/delete_list/<int:list_id>', methods=['POST'])
@login_required
def delete_list(list_id):
    lst = List.query.get_or_404(list_id)
    board_id = lst.board_id
    db.session.delete(lst)
    db.session.commit()
    flash("🗑️ List deleted successfully!")
    safe_emit('refresh_board', {'board_id': board_id})
    return redirect(url_for('view_board', board_id=board_id))

# ------------------ CARD CRUD ------------------
@app.route('/add_card/<int:list_id>', methods=['POST'])
@login_required
def add_card(list_id):
    title = request.form.get('title', '').strip()
    desc = request.form.get('description', '').strip()
    due_date_str = request.form.get('due_date')

    if not title:
        flash("⚠️ Card title cannot be empty.")
        return redirect(url_for('view_board', board_id=List.query.get(list_id).board_id))

    new_card = Card(title=title, description=desc, list_id=list_id)

    if due_date_str:
        try:
            new_card.due_date = datetime.strptime(due_date_str, "%Y-%m-%d")
        except ValueError:
            flash("⚠️ Invalid date format for due date. Use YYYY-MM-DD.")

    db.session.add(new_card)
    db.session.commit()
    flash("📝 Card added successfully!")
    safe_emit('refresh_board', {'board_id': new_card.list.board_id})
    return redirect(url_for('view_board', board_id=new_card.list.board_id))

@app.route('/update_due_date/<int:card_id>', methods=['POST'])
@login_required
def update_due_date(card_id):
    card = Card.query.get_or_404(card_id)
    date_str = request.form.get('due_date')

    if date_str:
        try:
            card.due_date = datetime.strptime(date_str, "%Y-%m-%d")
            db.session.commit()
            flash("✅ Due date updated!")
        except ValueError:
            flash("❌ Invalid date format (use YYYY-MM-DD).")
    else:
        card.due_date = None
        db.session.commit()
        flash("🗑️ Due date cleared.")

    return redirect(url_for('view_board', board_id=card.list.board_id))

@app.route('/update_card_status/<int:card_id>/<status>')
@login_required
def update_card_status(card_id, status):
    card = Card.query.get_or_404(card_id)
    if status not in ['Pending', 'Done']:
        flash("⚠️ Invalid status.")
        return redirect(url_for('view_board', board_id=card.list.board_id))

    card.status = status
    db.session.commit()
    flash(f"✅ Card marked as {status}.")
    safe_emit('refresh_board', {'board_id': card.list.board_id})
    return redirect(url_for('view_board', board_id=card.list.board_id))

# ------------------ COLLABORATOR FEATURE ------------------
@app.route('/add_collaborator/<int:board_id>', methods=['POST'])
@login_required
def add_collaborator(board_id):
    board = Board.query.get_or_404(board_id)
    username = request.form['username'].strip()
    user = User.query.filter_by(username=username).first()

    if not user:
        flash("❌ User not found.")
        return redirect(url_for('view_board', board_id=board_id))

    if user == board.owner:
        flash("⚠️ Owner is already part of the board.")
    elif user in board.collaborators:
        flash("⚠️ User already added.")
    else:
        board.collaborators.append(user)
        db.session.commit()
        flash(f"👥 {username} added as collaborator!")

    return redirect(url_for('view_board', board_id=board_id))

# ------------------ COMMENT FEATURE ------------------
@app.route('/add_comment/<int:card_id>', methods=['POST'])
@login_required
def add_comment(card_id):
    content = request.form.get('comment', '').strip()
    if not content:
        flash("⚠️ Comment cannot be empty.")
        return redirect(url_for('view_board', board_id=Card.query.get(card_id).list.board_id))

    new_comment = Comment(content=content, card_id=card_id, user_id=current_user.id)
    db.session.add(new_comment)
    db.session.commit()
    flash("💬 Comment added!")
    safe_emit('refresh_board', {'board_id': new_comment.card.list.board_id})
    return redirect(url_for('view_board', board_id=new_comment.card.list.board_id))

# ------------------ BOARD STATS ------------------
@app.route('/board_stats/<int:board_id>')
@login_required
def board_stats(board_id):
    board = Board.query.get_or_404(board_id)
    total_cards = Card.query.join(List).filter(List.board_id == board_id).count()
    completed = Card.query.join(List).filter(List.board_id == board_id, Card.status == 'Done').count()
    pending = total_cards - completed
    overdue = Card.query.join(List).filter(
        List.board_id == board_id,
        Card.due_date < datetime.utcnow(),
        Card.status != 'Done'
    ).count()

    return jsonify({
        "total_cards": total_cards,
        "completed": completed,
        "pending": pending,
        "overdue": overdue
    })

# ------------------ ANALYTICS PAGE ------------------
@app.route('/analytics')
@login_required
def analytics():
    boards = Board.query.filter_by(user_id=current_user.id).all()
    total_boards = len(boards)
    total_lists = sum(len(b.lists) for b in boards)
    total_cards = sum(len(lst.cards) for b in boards for lst in b.lists)
    completed_cards = sum(
        1 for b in boards for lst in b.lists for c in lst.cards if c.status == 'Done'
    )
    pending_cards = total_cards - completed_cards
    overdue_cards = sum(
        1 for b in boards for lst in b.lists for c in lst.cards
        if c.due_date and c.due_date < datetime.utcnow() and c.status != 'Done'
    )
    board_names = [b.name for b in boards]
    completed_cards_per_board = [sum(1 for lst in b.lists for c in lst.cards if c.status=='Done') for b in boards]
    pending_cards_per_board = [sum(1 for lst in b.lists for c in lst.cards if c.status=='Pending') for b in boards]
    overdue_cards_per_board = [sum(1 for lst in b.lists for c in lst.cards if c.due_date and c.due_date < datetime.utcnow() and c.status!='Done') for b in boards]

    return render_template('analytics.html',
                           total_boards=total_boards,
                           total_lists=total_lists,
                           total_cards=total_cards,
                           completed_cards=completed_cards,
                           pending_cards=pending_cards,
                           overdue_cards=overdue_cards,
                           board_names=board_names,
                           completed_cards_per_board=completed_cards_per_board,
                           pending_cards_per_board=pending_cards_per_board,
                           overdue_cards_per_board=overdue_cards_per_board)

# ------------------ RUN APP ------------------
if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        print("✅ Database ready. App running with Lists, Cards, Collaborators, Comments & Stats.")
    socketio.run(app, debug=True)
