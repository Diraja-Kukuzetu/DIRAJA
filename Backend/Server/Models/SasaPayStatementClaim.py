# Server/Models/SasaPayStatementClaim.py

from app import db


class SasaPayStatementClaim(db.Model):
    """
    One row per SasaPay statement transaction that has been turned into a sale.

    - One sale can claim many transactions (sale_id is NOT unique).
    - One transaction can be claimed only once (unique merchant_code + transaction_code).
    - Deleting the sale releases its claims (ON DELETE CASCADE at DB level).
    """
    __tablename__ = "sasapay_statement_claims"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    merchant_code = db.Column(db.String(20), nullable=False)
    transaction_code = db.Column(db.String(50), nullable=False)
    sale_id = db.Column(
        db.Integer,
        db.ForeignKey("sales.sales_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    shop_id = db.Column(db.Integer, nullable=True)
    amount = db.Column(db.Float, nullable=True)
    claimed_by = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime, server_default=db.func.now())

    __table_args__ = (
        db.UniqueConstraint(
            "merchant_code", "transaction_code", name="uq_statement_claim"
        ),
    )

    def __repr__(self):
        return (
            f"SasaPayStatementClaim(merchant_code='{self.merchant_code}', "
            f"transaction_code='{self.transaction_code}', sale_id={self.sale_id})"
        )