from flask_sqlalchemy import SQLAlchemy
from app import db
from sqlalchemy.orm import validates

class SoldItem(db.Model):
    __tablename__ = "sold_items"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    sales_id = db.Column(db.Integer, db.ForeignKey('sales.sales_id'), nullable=False)
    item_name = db.Column(db.String(50), nullable=False)
    item_id = db.Column(db.Integer, db.ForeignKey('stock_item.id'), nullable=False)
    quantity = db.Column(db.Float, nullable=False)
    metric = db.Column(db.String(10), nullable=False)
    unit_price = db.Column(db.Float, nullable=False)
    total_price = db.Column(db.Float, nullable=False)
    round_off = db.Column(db.Float)
    BatchNumber = db.Column(db.String(255), nullable=False)
    stockv2_id = db.Column(db.Integer, db.ForeignKey('shop_stock_v2.stockv2_id'), nullable=False)  # Updated reference
    Cost_of_sale = db.Column(db.Float, nullable=False)
    Purchase_account = db.Column(db.Float, nullable=False)
    LivestockDeduction = db.Column(db.Float, default=0.0)
    etims_item_code = db.Column(db.String(50), nullable=True)

    # Updated relationship to point to ShopStockV2
    shop_stock = db.relationship('ShopStockV2', backref='sold_items', lazy=True)
    stock_item = db.relationship('StockItems', backref='sold_items', lazy=True)
    is_service = db.Column(db.Boolean, default=False, nullable=False)
    @validates('metric')
    def validate_metric(self, key, metric):
        valid_metric = ['item','pieces', 'kg', 'ltrs']
        if metric is not None:
            assert metric in valid_metric, f"Invalid metric. Must be one of: {', '.join(valid_metric)}"
        return metric

    def __repr__(self):
        return f"<SoldItem id={self.id}, item={self.item_name}, quantity={self.quantity}>"