from flask_sqlalchemy import SQLAlchemy
from app import db
import bcrypt
from sqlalchemy.orm import validates
from sqlalchemy import func
from datetime import datetime
import secrets
import string


class Users(db.Model):
    __tablename__ = "users"
    
    #Table columns
    users_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    username = db.Column(db.String(50), unique=False, nullable=False)
    email = db.Column(db.String(50), unique=True, nullable=False)
    role = db.Column(db.String(50), default="manager", nullable=False)
    password = db.Column(db.String(200), unique=True, nullable=False)
    employee_id = db.Column(db.Integer, db.ForeignKey('employees.employee_id'))
    created_at = db.Column(db.DateTime, server_default=db.func.now())
    status = db.Column(db.String(10), default="inactive", nullable=False)
    
    # 2FA Fields - NEW
    two_factor_enabled = db.Column(db.Boolean, default=False, nullable=False)
    two_factor_secret = db.Column(db.String(255), nullable=True)
    two_factor_verified = db.Column(db.Boolean, default=False, nullable=False)
    two_factor_setup_date = db.Column(db.DateTime, nullable=True)
    backup_codes = db.Column(db.JSON, nullable=True)  # Store backup codes as JSON array

    #users relationship
    employees = db.relationship('Employees', backref='users', lazy=True)
    
    # 2FA relationship
    two_factor_codes = db.relationship('TwoFactorAuth', backref='user', lazy=True, cascade='all, delete-orphan')

    @validates('status')
    def validate_status(self, key, status):
        valid_status = ["active", "inactive", "former employee"]
        if status not in valid_status:
            raise ValueError(f"Invalid status. Must be one of: {', '.join(valid_status)}")
        return status

    # Data validation
    @validates('email')
    def validate_email(self, key, email):
        assert '@' in email, "Email address must contain the @ symbol."
        assert '.' in email.split('@')[-1], "Email address must have a valid domain name."
        return email
    
    def hash_password(self, password):
        # Hash the password using bcrypt
        salt = bcrypt.gensalt()
        hashed_password = bcrypt.hashpw(password.encode('utf-8'), salt)
        return hashed_password.decode('utf-8')
    
    @validates('role')
    def validate_role(self, key, role):
        valid_roles = ['manager', 'clerk', 'super_admin', 'procurement']
        assert role in valid_roles, f"Invalid role. Must be one of: {', '.join(valid_roles)}"
        return role
    
    @validates('password')
    def validate_password(self, key, password):
        error_messages = []

        if len(password) < 8:
            error_messages.append("Password must be at least 8 characters long.")

        if not any(char.isupper() for char in password):
            error_messages.append("Password must contain at least one capital letter.")

        if not any(char.isdigit() for char in password):
            error_messages.append("Password must contain at least one number.")
            
        if error_messages:
            raise AssertionError(" ".join(error_messages))

        return self.hash_password(password)
    
    # 2FA Methods - NEW
    def generate_2fa_code(self):
        """Generate a 6-digit 2FA code"""
        return ''.join(secrets.choice(string.digits) for _ in range(6))
    
    def generate_2fa_secret(self):
        """Generate a random secret for 2FA"""
        return secrets.token_hex(32)
    
    def generate_backup_codes(self, count=5):
        """Generate backup codes for 2FA recovery"""
        backup_codes = []
        for _ in range(count):
            # Generate 8-character alphanumeric codes
            code = ''.join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(8))
            backup_codes.append(code)
        return backup_codes
    
    def enable_2fa(self):
        """Enable 2FA for the user"""
        self.two_factor_enabled = True
        self.two_factor_secret = self.generate_2fa_secret()
        self.two_factor_setup_date = datetime.utcnow()
        self.two_factor_verified = False
        # Generate backup codes
        self.backup_codes = self.generate_backup_codes()
        db.session.commit()
        return self.backup_codes
    
    def verify_2fa_setup(self):
        """Mark 2FA as verified after successful test"""
        self.two_factor_verified = True
        db.session.commit()
    
    def disable_2fa(self):
        """Disable 2FA for the user"""
        self.two_factor_enabled = False
        self.two_factor_secret = None
        self.two_factor_verified = False
        self.two_factor_setup_date = None
        self.backup_codes = None
        db.session.commit()
    
    def verify_backup_code(self, code):
        """Verify if a backup code is valid and remove it"""
        if not self.backup_codes:
            return False
        
        if code in self.backup_codes:
            self.backup_codes.remove(code)
            db.session.commit()
            return True
        
        return False
    
    def has_role(self, role):
        return self.role == role
    
    def __repr__(self):
        return f"User(id={self.users_id}, username='{self.username}', email='{self.email}', role='{self.role}', status='{self.status}', two_factor_enabled={self.two_factor_enabled})"