from app import db
import datetime
from sqlalchemy.orm import validates


class TaskManager(db.Model):
    __tablename__ = "task_manager"

    task_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.users_id'), nullable=False)  # Assigner
    assignee_id = db.Column(db.Integer, db.ForeignKey('users.users_id'), nullable=False)  # Assignee
    task = db.Column(db.String(255), nullable=False)
    assigned_date = db.Column(db.DateTime, default=datetime.datetime.utcnow, nullable=False)
    due_date = db.Column(db.DateTime, nullable=True)
    status = db.Column(db.String(50), default="Pending", nullable=False)
    priority = db.Column(db.String(50), nullable=False)
    category = db.Column(db.String(50), nullable=False, default="General")
    closing_date = db.Column(db.DateTime, nullable=True)
    
    # Relationships - using select lazy loading to allow eager loading
    assigner = db.relationship('Users', foreign_keys=[user_id], backref='assigned_tasks', lazy='select')
    assignee = db.relationship('Users', foreign_keys=[assignee_id], backref='received_tasks', lazy='select')
    comments = db.relationship(
        'TaskComment', 
        backref='task', 
        lazy='select',  # Changed from 'dynamic' to allow eager loading
        cascade='all, delete-orphan',
        order_by='TaskComment.created_at.desc()'
    )
    evaluation = db.relationship(
        'TaskEvaluation', 
        backref='task', 
        uselist=False, 
        lazy='select',
        cascade='all, delete-orphan'
    )
    
    @validates('priority')
    def validate_priority(self, key, priority):
        valid_priorities = ['High', 'Medium', 'Low']
        assert priority in valid_priorities, f"Invalid priority. Must be one of: {', '.join(valid_priorities)}"
        return priority
    
    @validates('category')
    def validate_category(self, key, category):
        valid_categories = ['General', 'Delivery', 'Cleaning', 'Maintenance', 'Office Work', 'Field Work', 'Other']
        assert category in valid_categories, f"Invalid category. Must be one of: {', '.join(valid_categories)}"
        return category
    
    @validates('status')
    def validate_status(self, key, status):
        valid_statuses = ['Pending', 'In Progress', 'Completed', 'Cancelled', 'Overdue']
        assert status in valid_statuses, f"Invalid status. Must be one of: {', '.join(valid_statuses)}"
        return status
    
    @property
    def is_overdue(self):
        """Check if task is overdue"""
        if self.due_date and self.status not in ['Completed', 'Cancelled']:
            return datetime.datetime.utcnow() > self.due_date
        return False
    
    @property
    def comment_count(self):
        """Get number of comments on this task"""
        return len(self.comments) if self.comments else 0
    
    def complete_task(self, closing_date=None):
        """Mark task as completed"""
        self.status = 'Completed'
        self.closing_date = closing_date or datetime.datetime.utcnow()
    
    def to_dict(self, include_comments=False, include_evaluation=False):
        """Convert task object to dictionary for JSON serialization"""
        data = {
            "task_id": self.task_id,
            "assigner_id": self.user_id,
            "assigner_username": self.assigner.username if self.assigner else "Unknown",
            "assignee_id": self.assignee_id,
            "assignee_username": self.assignee.username if self.assignee else "Unknown",
            "task": self.task,
            "priority": self.priority,
            "category": self.category,
            "status": self.status,
            "assigned_date": self.assigned_date.isoformat() if self.assigned_date else None,
            "due_date": self.due_date.isoformat() if self.due_date else None,
            "closing_date": self.closing_date.isoformat() if self.closing_date else None,
            "is_overdue": self.is_overdue,
            "comment_count": self.comment_count,
        }
        
        # Include comments if requested - only top-level comments
        if include_comments and self.comments:
            top_level_comments = [c for c in self.comments if c.parent_comment_id is None]
            data["comments"] = [c.to_dict(include_replies=True) for c in top_level_comments]
        
        # Include evaluation if requested
        if include_evaluation and self.evaluation:
            data["evaluation"] = self.evaluation.to_dict()
        
        return data
    
    def __repr__(self):
        return (f"TaskManager(task_id={self.task_id}, user_id={self.user_id}, assignee_id={self.assignee_id}, "
                f"task='{self.task}', category='{self.category}', priority='{self.priority}', "
                f"status='{self.status}', due_date='{self.due_date}')")


class TaskComment(db.Model):
    __tablename__ = "task_comments"
    
    comment_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    task_id = db.Column(db.Integer, db.ForeignKey('task_manager.task_id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.users_id'), nullable=False)
    comment = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, onupdate=datetime.datetime.utcnow)
    
    # For replies (self-referential relationship)
    parent_comment_id = db.Column(db.Integer, db.ForeignKey('task_comments.comment_id'), nullable=True)
    
    # Relationships - using select lazy loading
    replies = db.relationship(
        'TaskComment', 
        backref=db.backref('parent', remote_side=[comment_id]),
        lazy='select',  # Changed from 'dynamic' to allow eager loading
        cascade='all, delete-orphan'
    )
    
    user = db.relationship('Users', backref='task_comments', lazy='select')
    
    @property
    def is_reply(self):
        """Check if this comment is a reply to another comment"""
        return self.parent_comment_id is not None
    
    @property
    def reply_count(self):
        """Get number of replies to this comment"""
        return len(self.replies) if self.replies else 0
    
    def to_dict(self, include_replies=False):
        """Convert comment object to dictionary for JSON serialization"""
        data = {
            "comment_id": self.comment_id,
            "task_id": self.task_id,
            "user_id": self.user_id,
            "username": self.user.username if self.user else "Unknown",
            "comment": self.comment,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "parent_comment_id": self.parent_comment_id,
            "is_reply": self.is_reply,
            "reply_count": self.reply_count,
        }
        
        # Include replies if requested
        if include_replies and self.replies:
            data["replies"] = [reply.to_dict(include_replies=False) for reply in self.replies]
        
        return data
    
    def __repr__(self):
        return (f"TaskComment(comment_id={self.comment_id}, task_id={self.task_id}, "
                f"user_id={self.user_id}, created_at='{self.created_at}')")


class TaskEvaluation(db.Model):
    __tablename__ = "task_evaluations"
    
    evaluation_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    task_id = db.Column(db.Integer, db.ForeignKey('task_manager.task_id'), nullable=False, unique=True)
    evaluator_id = db.Column(db.Integer, db.ForeignKey('users.users_id'), nullable=False)
    rating = db.Column(db.Integer, nullable=True)
    comment = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow, nullable=False)
    
    # Relationships
    evaluator = db.relationship('Users', foreign_keys=[evaluator_id], backref='task_evaluations_given', lazy='select')
    
    @validates('rating')
    def validate_rating(self, key, rating):
        if rating is not None:
            assert 1 <= rating <= 5, "Rating must be between 1 and 5"
        return rating
    
    def to_dict(self):
        """Convert evaluation object to dictionary for JSON serialization"""
        return {
            "evaluation_id": self.evaluation_id,
            "task_id": self.task_id,
            "evaluator_id": self.evaluator_id,
            "evaluator_name": self.evaluator.username if self.evaluator else "Unknown",
            "rating": self.rating,
            "comment": self.comment,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
    
    def __repr__(self):
        return (f"TaskEvaluation(evaluation_id={self.evaluation_id}, task_id={self.task_id}, "
                f"rating={self.rating}, created_at='{self.created_at}')")