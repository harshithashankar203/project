from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime, date

db = SQLAlchemy()

# ---- User Model ----
class User(UserMixin, db.Model):
    __tablename__ = 'user'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    boards = db.relationship('Board', backref='owner', cascade="all, delete", lazy=True)


# ---- Board Model ----
class Board(db.Model):
    __tablename__ = 'board'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    date_created = db.Column(db.DateTime, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete="CASCADE"), nullable=False)
    lists = db.relationship('List', backref='board', cascade="all, delete", lazy=True)


# ---- List Model ----
class List(db.Model):
    __tablename__ = 'list'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    board_id = db.Column(db.Integer, db.ForeignKey('board.id', ondelete="CASCADE"), nullable=False)
    cards = db.relationship('Card', backref='list', cascade="all, delete", lazy=True)


# ---- Card Model ----
class Card(db.Model):
    __tablename__ = 'card'
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    position = db.Column(db.Integer, default=0)
    status = db.Column(db.String(20), default='Pending')
    due_date = db.Column(db.Date, nullable=True)  # ⏰ NEW FEATURE: Due Date
    date_created = db.Column(db.DateTime, default=datetime.utcnow)
    list_id = db.Column(db.Integer, db.ForeignKey('list.id', ondelete="CASCADE"), nullable=False)

    # Helper function to check if card is overdue
    def is_overdue(self):
        if self.due_date and self.due_date < date.today() and self.status != 'Done':
            return True
        return False

    # Helper function to check if card is due today
    def is_due_today(self):
        if self.due_date and self.due_date == date.today():
            return True
        return False
