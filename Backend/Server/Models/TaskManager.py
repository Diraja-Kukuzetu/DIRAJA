from app import db
import datetime
from sqlalchemy.orm import validates
from sqlalchemy import event
import json

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
    
    # Recurring task fields
    is_recurring = db.Column(db.Boolean, default=False, nullable=False)
    recurrence_pattern = db.Column(db.String(50), nullable=True)  # 'daily', 'weekly', 'monthly', 'yearly'
    recurrence_interval = db.Column(db.Integer, default=1, nullable=True)  # Every X days/weeks/months/years
    recurrence_end_date = db.Column(db.DateTime, nullable=True)  # When to stop recurring
    last_recurrence_date = db.Column(db.DateTime, nullable=True)  # Last time task was regenerated
    parent_task_id = db.Column(db.Integer, db.ForeignKey('task_manager.task_id'), nullable=True)  # For recurring task chain
    recurrence_count = db.Column(db.Integer, default=0, nullable=True)  # Number of times regenerated
    max_recurrences = db.Column(db.Integer, nullable=True)  # Max number of times to regenerate
    
    # Relationships - using select lazy loading to allow eager loading
    assigner = db.relationship('Users', foreign_keys=[user_id], backref='assigned_tasks', lazy='select')
    assignee = db.relationship('Users', foreign_keys=[assignee_id], backref='received_tasks', lazy='select')
    comments = db.relationship(
        'TaskComment', 
        backref='task', 
        lazy='select',
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
    
    # Self-referential relationship for recurring tasks
    parent_task = db.relationship('TaskManager', remote_side=[task_id], backref='child_tasks', foreign_keys=[parent_task_id])
    
    @validates('priority')
    def validate_priority(self, key, priority):
        valid_priorities = ['High', 'Medium', 'Low']
        assert priority in valid_priorities, f"Invalid priority. Must be one of: {', '.join(valid_priorities)}"
        return priority
    
    @validates('status')
    def validate_status(self, key, status):
        valid_statuses = ['Pending', 'In Progress', 'Complete', 'Cancelled', 'Overdue']
        assert status in valid_statuses, f"Invalid status. Must be one of: {', '.join(valid_statuses)}"
        return status
    
    @validates('recurrence_pattern')
    def validate_recurrence_pattern(self, key, pattern):
        if pattern is not None:
            valid_patterns = ['daily', 'weekly', 'monthly', 'yearly']
            assert pattern in valid_patterns, f"Invalid recurrence pattern. Must be one of: {', '.join(valid_patterns)}"
        return pattern
    
    @property
    def is_overdue(self):
        """Check if task is overdue"""
        if self.due_date and self.status not in ['Complete', 'Cancelled']:
            return datetime.datetime.utcnow() > self.due_date
        return False
    
    @property
    def comment_count(self):
        """Get number of comments on this task"""
        return len(self.comments) if self.comments else 0
    
    @property
    def should_regenerate(self):
        """Check if recurring task should be regenerated"""
        if not self.is_recurring:
            return False
        
        if self.status in ['Complete', 'Cancelled']:
            return False
        
        if self.recurrence_end_date and datetime.datetime.utcnow() > self.recurrence_end_date:
            return False
        
        if self.max_recurrences and self.recurrence_count >= self.max_recurrences:
            return False
        
        # Check if it's time to regenerate based on pattern
        if self.last_recurrence_date:
            next_due_date = self.calculate_next_due_date(self.last_recurrence_date)
            return datetime.datetime.utcnow() >= next_due_date
        elif self.due_date:
            # If never regenerated before, check if due date has passed
            return datetime.datetime.utcnow() > self.due_date
        
        return False
    
    def calculate_next_due_date(self, from_date):
        """Calculate next due date based on recurrence pattern"""
        if not self.recurrence_pattern:
            return None
        
        next_date = from_date
        
        if self.recurrence_pattern == 'daily':
            next_date = from_date + datetime.timedelta(days=self.recurrence_interval)
        elif self.recurrence_pattern == 'weekly':
            next_date = from_date + datetime.timedelta(weeks=self.recurrence_interval)
        elif self.recurrence_pattern == 'monthly':
            # Handle month addition carefully
            month = from_date.month + self.recurrence_interval
            year = from_date.year + (month - 1) // 12
            month = ((month - 1) % 12) + 1
            # Keep the same day, but handle month boundaries
            day = min(from_date.day, [31, 29 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0) else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1])
            next_date = from_date.replace(year=year, month=month, day=day)
        elif self.recurrence_pattern == 'yearly':
            next_date = from_date.replace(year=from_date.year + self.recurrence_interval)
        
        return next_date
    
    def regenerate_recurring_task(self, mark_as_complete=False):
        """Create a new task instance for the next recurrence
        
        Args:
            mark_as_complete: If True, marks the current task as Complete.
                            If False, leaves current task unchanged (for batch processing).
        """
        if not self.should_regenerate:
            return None
        
        # Calculate new due date based on the current due date or assigned date
        base_date = self.due_date or self.assigned_date
        new_due_date = self.calculate_next_due_date(base_date)
        
        # Create new task instance with same credentials
        new_task = TaskManager(
            user_id=self.user_id,  # Same assigner
            assignee_id=self.assignee_id,  # Same assignee
            task=self.task,  # Same task description
            assigned_date=datetime.datetime.utcnow(),
            due_date=new_due_date,
            priority=self.priority,
            category=self.category,
            status='Pending',  # New task starts as Pending
            is_recurring=True,
            recurrence_pattern=self.recurrence_pattern,
            recurrence_interval=self.recurrence_interval,
            recurrence_end_date=self.recurrence_end_date,
            parent_task_id=self.task_id,  # Link to parent task
            recurrence_count=self.recurrence_count + 1,
            max_recurrences=self.max_recurrences,
            last_recurrence_date=datetime.datetime.utcnow()
        )
        
        db.session.add(new_task)
        
        # Update the current task's last_recurrence_date
        self.last_recurrence_date = datetime.datetime.utcnow()
        
        # Optionally mark current task as complete
        if mark_as_complete:
            self.status = 'Complete'
            self.closing_date = datetime.datetime.utcnow()
        
        return new_task
    
    def complete_task(self, closing_date=None):
        """Mark task as completed and regenerate next instance if recurring"""
        self.status = 'Complete'
        self.closing_date = closing_date or datetime.datetime.utcnow()
        
        # If this is a recurring task, regenerate next instance
        if self.is_recurring and self.should_regenerate:
            return self.regenerate_recurring_task(mark_as_complete=False)  # Don't mark again, it's already Complete
        
        return None
    
    def cancel_recurring_task(self):
        """Cancel a recurring task and prevent future regenerations"""
        self.status = 'Cancelled'
        self.closing_date = datetime.datetime.utcnow()
        self.is_recurring = False  # Stop future regenerations
    
    def to_dict(self, include_comments=False, include_evaluation=False, include_recurrence_info=False):
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
            "is_recurring": self.is_recurring,
        }
    
        if include_recurrence_info:
            data["recurrence"] = {
                "is_recurring": self.is_recurring,
                "recurrence_pattern": self.recurrence_pattern,
                "recurrence_interval": self.recurrence_interval,
                "recurrence_end_date": self.recurrence_end_date.isoformat() if self.recurrence_end_date else None,
                "last_recurrence_date": self.last_recurrence_date.isoformat() if self.last_recurrence_date else None,
                "parent_task_id": self.parent_task_id,
                "recurrence_count": self.recurrence_count,
                "max_recurrences": self.max_recurrences,
                "should_regenerate": self.should_regenerate,
            }
    
        if include_comments and self.comments:
            top_level_comments = [c for c in self.comments if c.parent_comment_id is None]
            data["comments"] = [c.to_dict(include_replies=True) for c in top_level_comments]
    
        if include_evaluation and self.evaluation:
            data["evaluation"] = self.evaluation.to_dict()
    
        return data

    
    def __repr__(self):
        return (f"TaskManager(task_id={self.task_id}, user_id={self.user_id}, assignee_id={self.assignee_id}, "
                f"task='{self.task}', category='{self.category}', priority='{self.priority}', "
                f"status='{self.status}', due_date='{self.due_date}', is_recurring={self.is_recurring})")


# Database event listener to automatically regenerate recurring tasks
@event.listens_for(TaskManager, 'after_update')
def check_recurring_task_regeneration(mapper, connection, target):
    """After a task is updated, check if it should regenerate a new instance"""
    # This runs after the task is updated in the database
    # We need to use a separate session to avoid recursion issues
    if target.is_recurring and target.status == 'Complete' and target.should_regenerate:
        # The regeneration happens in complete_task method
        # This event listener is for additional logic if needed
        pass


# Helper function to process recurring tasks (UPDATED)
def process_recurring_tasks():
    """Process all recurring tasks that need regeneration (not just overdue)"""
    from app import create_app
    app = create_app()
    
    with app.app_context():
        # Get all active recurring tasks (incomplete and not cancelled)
        recurring_tasks = TaskManager.query.filter(
            TaskManager.is_recurring == True,
            TaskManager.status.in_(['Pending', 'In Progress', 'Overdue'])
        ).all()
        
        regenerated_count = 0
        for task in recurring_tasks:
            if task.should_regenerate:
                # Don't mark the current task as complete in batch processing
                # This allows the task to remain active while a new one is created
                new_task = task.regenerate_recurring_task(mark_as_complete=False)
                if new_task:
                    regenerated_count += 1
        
        if regenerated_count > 0:
            db.session.commit()
        
        return regenerated_count


# Keep the old function for backward compatibility if needed
def process_overdue_recurring_tasks():
    """Background job to process overdue recurring tasks and regenerate them"""
    from app import create_app
    app = create_app()
    
    with app.app_context():
        # Find all incomplete recurring tasks that should be regenerated
        overdue_tasks = TaskManager.query.filter(
            TaskManager.is_recurring == True,
            TaskManager.status.in_(['Pending', 'In Progress', 'Overdue']),
            TaskManager.due_date < datetime.datetime.utcnow()
        ).all()
        
        regenerated_tasks = []
        for task in overdue_tasks:
            if task.should_regenerate:
                new_task = task.regenerate_recurring_task(mark_as_complete=False)
                if new_task:
                    regenerated_tasks.append(new_task)
        
        if regenerated_tasks:
            db.session.commit()
        
        return len(regenerated_tasks)


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