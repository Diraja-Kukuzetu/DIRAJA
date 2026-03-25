from  flask_restful import Resource,reqparse
from Server.Models.ChartOfAccounts import ChartOfAccounts
from app import db 
from flask import request,make_response,jsonify
from flask_jwt_extended import jwt_required
from Server.Models.Inventory import Inventory
from Server.Models.Sales import Sales
from Server.Models.Users import Users
from Server.Models.Shops import Shops
from Server.Models.ItemsLists import ItemsList

# class CreateAccount(Resource):
#     @jwt_required()
#     def post(self):
#         data = request.get_json()

#         name = data.get('name')
#         type_ = data.get('type')

#         if not name or not type_:
#             return make_response(jsonify({"message": "Both 'name' and 'type' are required."}), 400)

#         new_type = AccountTypes(name=name, type=type_)

#         try:
#             db.session.add(new_type)
#             db.session.commit()
#             return make_response(jsonify({
#                 "message": "Account type created successfully.",
#                 "account_type": {
#                     "id": new_type.id,
#                     "name": new_type.name,
#                     "type": new_type.type
#                 }
#             }), 201)
#         except Exception as e:
#             db.session.rollback()
#             return make_response(jsonify({"message": "Error creating account type.", "error": str(e)}), 500)

        
# class AccountTypeListResource(Resource):
#     @jwt_required()
#     def get(self):
#         try:
#             account_types = AccountTypes.query.all()
#             results = [
#                 {
#                     "id": acct.id,
#                     "name": acct.name,
#                     "type": acct.type
#                 } for acct in account_types
#             ]
#             return make_response(jsonify(results), 200)
#         except Exception as e:
#             return make_response(jsonify({
#                 "message": "Error fetching account types.",
#                 "error": str(e)
#             }), 500)
        
# class AccountTypeResource(Resource):
#     # GET an account type by ID
#     @jwt_required()
#     def get(self, id):
#         account_type = AccountTypes.query.get(id)
        
#         if not account_type:
#             return make_response(jsonify({"message": "Account type not found."}), 404)
        
#         return make_response(jsonify({
#             "id": account_type.id,
#             "name": account_type.name,
#             "type": account_type.type
#         }), 200)

#     # PUT (update) an account type by ID
#     @jwt_required()
#     def put(self, id):
#         data = request.get_json()
#         account_type = AccountTypes.query.get(id)

#         if not account_type:
#             return make_response(jsonify({"message": "Account type not found."}), 404)

#         name = data.get('name', account_type.name)
#         type_ = data.get('type', account_type.type)

#         # Check if the type already exists
#         if AccountTypes.query.filter_by(type=type_).first() and type_ != account_type.type:
#             return make_response(jsonify({"message": f"Account type '{type_}' already exists."}), 409)

#         account_type.name = name
#         account_type.type = type_

#         try:
#             db.session.commit()
#             return make_response(jsonify({
#                 "message": "Account type updated successfully.",
#                 "account_type": {
#                     "id": account_type.id,
#                     "name": account_type.name,
#                     "type": account_type.type
#                 }
#             }), 200)
#         except Exception as e:
#             db.session.rollback()
#             return make_response(jsonify({"message": "Error updating account type.", "error": str(e)}), 500)

#     # DELETE an account type by ID
#     @jwt_required()
#     def delete(self, id):
#         account_type = AccountTypes.query.get(id)

#         if not account_type:
#             return make_response(jsonify({"message": "Account type not found."}), 404)

#         try:
#             db.session.delete(account_type)
#             db.session.commit()
#             return make_response(jsonify({"message": "Account type deleted successfully."}), 200)
#         except Exception as e:
#             db.session.rollback()
#             return make_response(jsonify({"message": "Error deleting account type.", "error": str(e)}), 500)
        
#chat of aacounts 



class CreateChartOfAccounts(Resource):
    # POST a new chart of account entry
    @jwt_required()
    def post(self):
        data = request.get_json()

        # Extract fields
        code = data.get('code')
        name = data.get('name')
        acc_type = data.get('type')
        statement_type = data.get('statement_type')
        transaction_type = data.get('transaction_type')

        # Validate required fields
        if not code or not name or not acc_type or not statement_type or not transaction_type:
            return make_response(jsonify({
                "message": "Code, name, type, statement_type, and transaction_type are required."
            }), 400)

        try:
            new_chart_of_account = ChartOfAccounts(
                code=code,
                name=name,
                type=acc_type,
                statement_type=statement_type,
                transaction_type=transaction_type
            )

            db.session.add(new_chart_of_account)
            db.session.commit()

            return make_response(jsonify({
                "message": "Chart of account created successfully.",
                "chart_of_account": {
                    "id": new_chart_of_account.id,
                    "code": new_chart_of_account.code,
                    "name": new_chart_of_account.name,
                    "type": new_chart_of_account.type,
                    "statement_type": new_chart_of_account.statement_type,
                    "transaction_type": new_chart_of_account.transaction_type
                }
            }), 201)
            
        except AssertionError as e:
            db.session.rollback()
            return make_response(jsonify({"message": str(e)}), 400)
        except Exception as e:
            db.session.rollback()
            return make_response(jsonify({"message": "Error creating chart of account.", "error": str(e)}), 500)


class ChartOfAccountsList(Resource):
    # GET all chart of account entries
    @jwt_required()
    def get(self):
        try:
            chart_of_accounts = ChartOfAccounts.query.all()

            if not chart_of_accounts:
                return make_response(jsonify({"message": "No chart of accounts found."}), 404)

            result = []
            for account in chart_of_accounts:
                result.append({
                    "id": account.id,
                    "code": account.code,
                    "name": account.name,
                    "type": account.type,
                    "statement_type": account.statement_type,
                    "transaction_type": account.transaction_type
                })

            return make_response(jsonify({"chart_of_accounts": result}), 200)

        except Exception as e:
            return make_response(jsonify({"message": "Error fetching chart of accounts.", "error": str(e)}), 500)


class ChartOfAccountResource(Resource):
    @jwt_required()
    def get(self, id):
        account = ChartOfAccounts.query.get(id)
        if not account:
            return make_response(jsonify({"message": "Chart of Account not found"}), 404)

        return make_response(jsonify({
            "id": account.id,
            "code": account.code,
            "name": account.name,
            "type": account.type,
            "statement_type": account.statement_type,
            "transaction_type": account.transaction_type
        }), 200)

    @jwt_required()
    def put(self, id):
        parser = reqparse.RequestParser()
        parser.add_argument('code', type=str, required=True, help='Code is required')
        parser.add_argument('name', type=str, required=True, help='Name is required')
        parser.add_argument('type', type=str, required=True, help='Type is required')
        parser.add_argument('statement_type', type=str, required=True, help='Statement type is required')
        parser.add_argument('transaction_type', type=str, required=True, help='Transaction type is required')
        data = parser.parse_args()

        account = ChartOfAccounts.query.get(id)
        if not account:
            return make_response(jsonify({"message": "Chart of Account not found"}), 404)

        try:
            account.code = data['code']
            account.name = data['name']
            account.type = data['type']
            account.statement_type = data['statement_type']
            account.transaction_type = data['transaction_type']
            
            db.session.commit()

            return make_response(jsonify({
                "message": "Chart of Account updated successfully",
                "chart_of_account": {
                    "id": account.id,
                    "code": account.code,
                    "name": account.name,
                    "type": account.type,
                    "statement_type": account.statement_type,
                    "transaction_type": account.transaction_type
                }
            }), 200)
            
        except AssertionError as e:
            db.session.rollback()
            return make_response(jsonify({"message": str(e)}), 400)
        except Exception as e:
            db.session.rollback()
            return make_response(jsonify({"message": "Error updating chart of account.", "error": str(e)}), 500)

    @jwt_required()
    def delete(self, id):
        account = ChartOfAccounts.query.get(id)
        if not account:
            return make_response(jsonify({"message": "Chart of Account not found"}), 404)

        try:
            db.session.delete(account)
            db.session.commit()
            return make_response(jsonify({"message": "Chart of Account deleted successfully"}), 200)
        except Exception as e:
            db.session.rollback()
            return make_response(jsonify({"message": "Error deleting chart of account.", "error": str(e)}), 500)


# class CreateItemAccount(Resource):
#     @jwt_required()
#     def post(self):
#         data = request.get_json()

#         item = data.get('item')
#         chart_account_ids = data.get('chart_account_ids')  # Expecting a list of chart_of_accounts IDs

#         if not item or not isinstance(chart_account_ids, list) or not chart_account_ids:
#             return {"message": "Missing or invalid fields. 'item' and 'chart_account_ids' are required."}, 400

#         try:
#             # Create the item
#             new_item_account = ItemAccounts(item=item)

#             # Query chart accounts
#             chart_accounts = ChartOfAccounts.query.filter(ChartOfAccounts.id.in_(chart_account_ids)).all()

#             if not chart_accounts:
#                 return {"message": "No valid chart accounts found for given IDs."}, 400

#             # Assign the relationships
#             new_item_account.chart_accounts = chart_accounts

#             # Save to DB
#             db.session.add(new_item_account)
#             db.session.commit()

#             return {
#                 "message": "Item account created successfully.",
#                 "item_account": {
#                     "id": new_item_account.id,
#                     "item": new_item_account.item,
#                     "chart_accounts": [account.id for account in new_item_account.chart_accounts]
#                 }
#             }, 201

#         except Exception as e:
#             db.session.rollback()
#             return {"message": "An error occurred.", "error": str(e)}, 500

        
# class GetAllItemAccounts(Resource):
#     @jwt_required()
#     def get(self):
#         try:
#             items = ItemAccounts.query.all()
#             item_list = []
#             for item in items:
#                 # Collect the account names associated with this item account
#                 account_names = [account.Account for account in item.chart_accounts]

#                 item_list.append({
#                     "id": item.id,
#                     "item": item.item,
#                     "accounts": account_names  # Return list of associated account names
#                 })
                
#             return {"item_accounts": item_list}, 200

#         except Exception as e:
#             return {"message": "Failed to fetch item accounts", "error": str(e)}, 500


class PurchasesLedger(Resource):
    @jwt_required()
    def get(self):
        try:
            # 🔍 Only get inventories where Transcation_type_debit > 0
            inventories = Inventory.query.filter(Inventory.Transcation_type_debit > 0).order_by(Inventory.created_at.desc()).all()

            all_inventory = [{
                "suppliername": inventory.Suppliername,
                "itemname": inventory.itemname,
                "initial_quantity": inventory.initial_quantity,
                "remaining_quantity": inventory.quantity,
                "amountPaid": inventory.amountPaid,
                "balance": inventory.ballance,
                "created_at": inventory.created_at,
                "unitPrice": inventory.unitPrice,
                "source": inventory.source,
                "transcation_type_debit": inventory.Transcation_type_debit,
                "trasnaction_type_credit": inventory.Trasnaction_type_credit
            } for inventory in inventories]

            return make_response(jsonify(all_inventory), 200)

        except Exception as e:
            return {"error": str(e)}, 500



class SalesLedger(Resource):

    @jwt_required()
    def get(self):
        try:
            # Query sales where Purchase_account is greater than zero
            sales = Sales.query.filter(Sales.Purchase_account > 0).order_by(Sales.created_at.desc()).all()

            # If no sales found
            if not sales:
                return {"message": "No sales found"}, 404

            # Format sales data into a list of dictionaries
            sales_data = []
            for sale in sales:
                # Fetch username and shop name manually using user_id and shop_id
                user = Users.query.filter_by(users_id=sale.user_id).first()
                shop = Shops.query.filter_by(shops_id=sale.shop_id).first()

                # Handle cases where user or shop may not be found
                username = user.username if user else "Unknown User"
                shopname = shop.shopname if shop else "Unknown Shop"

                # Process multiple payment methods using the `payment` relationship
                payment_data = [
                    {
                        "payment_method": payment.payment_method,
                        "amount_paid": payment.amount_paid,
                        "created_at": payment.created_at,
                        "balance": payment.balance,  # Include balance field
                    }
                    for payment in sale.payment  # Using correct relationship
                ]

                # Calculate total amount paid
                total_amount_paid = sum(payment["amount_paid"] for payment in payment_data)

                sales_data.append({
                    "sale_id": sale.sales_id,
                    "user_id": sale.user_id,
                    "username": username,
                    "shop_id": sale.shop_id,
                    "shopname": shopname,
                    "customer_name": sale.customer_name,
                    "status": sale.status,
                    "customer_number": sale.customer_number,
                    "item_name": sale.item_name,
                    "quantity": sale.quantity,
                    "batchnumber": sale.BatchNumber,
                    "metric": sale.metric,
                    "unit_price": sale.unit_price,
                    "total_price": sale.total_price,
                    "total_amount_paid": total_amount_paid,
                    "payment_methods": payment_data,
                    "created_at": sale.created_at,
                    "balance": sale.balance,
                    "note": sale.note,
                    "Purchase_account": sale.Purchase_account,
                    "Cost_of_sale": sale.Cost_of_sale
                })

            return make_response(jsonify(sales_data), 200)

        except Exception as e:
            return {"error": str(e)}, 500


#items list 


class CreateItem(Resource):
    @jwt_required()
    def post(self):
        data = request.get_json()

        item_type = data.get('item_type')
        item_name = data.get('item_name')
        purchase_account = data.get('purchase_account')
        sales_account = data.get('sales_account')
        cost_of_sales_account = data.get('cost_of_sales_account')
        gl_account_id = data.get('gl_account_id')
        description = data.get('description')

        # ✅ Basic validation
        if not item_type:
            return make_response(jsonify({"message": "'item_type' is required."}), 400)
        if not item_name:
            return make_response(jsonify({"message": "'item_name' is required."}), 400)

        # ✅ Validate foreign keys if provided
        for field_name, account_id in {
            "purchase_account": purchase_account,
            "sales_account": sales_account,
            "cost_of_sales_account": cost_of_sales_account,
            "gl_account_id": gl_account_id
        }.items():
            if account_id is not None:
                if not ChartOfAccounts.query.get(account_id):
                    return make_response(
                        jsonify({"message": f"Invalid {field_name}: account {account_id} does not exist."}),
                        400
                    )

        # ✅ Create new item
        new_item = ItemsList(
            item_type=item_type,
            item_name=item_name,
            purchase_account=purchase_account,
            sales_account=sales_account,
            cost_of_sales_account=cost_of_sales_account,
            gl_account_id=gl_account_id,
            description=description
        )

        try:
            db.session.add(new_item)
            db.session.commit()
            return make_response(jsonify({
                "message": "Item created successfully.",
                "item": {
                    "id": new_item.item_id,
                    "type": new_item.item_type,
                    "name": new_item.item_name,
                    "purchase_account": new_item.purchase_account,
                    "sales_account": new_item.sales_account,
                    "cost_of_sales_account": new_item.cost_of_sales_account,
                    "gl_account_id": new_item.gl_account_id,
                    "description": new_item.description
                }
            }), 201)
        except Exception as e:
            db.session.rollback()
            return make_response(jsonify({
                "message": "Error creating item.",
                "error": str(e)
            }), 500)


    

class GetItems(Resource):
    def get(self):
        try:
            items = ItemsList.query.all()
            result = []

            for item in items:
                def get_account_info(account_id):
                    if account_id:
                        acc = ChartOfAccounts.query.get(account_id)
                        if acc:
                            return {"id": acc.id, "name": acc.name, "type": acc.type}
                    return None

                result.append({
                    "id": item.item_id,
                    "type": item.item_type,
                    "name": item.item_name,
                    "description": item.description,
                    "purchase_account": get_account_info(item.purchase_account),
                    "sales_account": get_account_info(item.sales_account),
                    "cost_of_sales_account": get_account_info(item.cost_of_sales_account),
                    "gl_account": get_account_info(item.gl_account_id),
                })

            return make_response(jsonify({"items": result}), 200)

        except Exception as e:
            return make_response(
                jsonify({"message": "Error fetching items", "error": str(e)}), 
                500
            )