from app import db
from sqlalchemy.orm import validates

class ChartOfAccounts(db.Model):
    __tablename__ = 'chart_of_accounts'

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(10), nullable=False, unique=True)
    name = db.Column(db.String(50), nullable=False, unique=True)
    type = db.Column(db.String(50), nullable=False)
    statement_type = db.Column(db.String(20), nullable=False)
    transaction_type = db.Column(db.String(10), nullable=False)

    @validates('statement_type')
    def validate_statement_type(self, key, value):
        valid_statements = ['Balance Sheet', 'Income Statement']
        assert value in valid_statements, f"statement_type must be one of {valid_statements}"
        return value

    @validates('transaction_type')
    def validate_transaction_type(self, key, value):
        valid_transactions = ['Debit', 'Credit']
        assert value in valid_transactions, f"transaction_type must be one of {valid_transactions}"
        return value

    @validates('type')
    def validate_type(self, key, value):
        valid_types = ['Asset', 'Liability', 'Equity', 'Revenue', 'Expense']
        assert value in valid_types, f"type must be one of {valid_types}"
        return value

    def __str__(self):
        return f"ChartOfAccounts(id={self.id}, code='{self.code}', name='{self.name}')"