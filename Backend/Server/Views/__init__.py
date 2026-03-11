from flask import Blueprint
from flask_restful import Api

api_endpoint = Blueprint 

# add all file inputs 
from Server.Views.Usersviews import (
    CountUsers, Addusers, UsersResourceById, UserLogin, GetAllUsers,PostShopReport
)

from Server.Views.Shopsviews import (
    AddShops, ShopsResourceById, GetAllShops, GetActiveShops
)

from Server.Views.Shopstockviews import (
    ShopStockDelete, GetShopStock, GetShopStockByShopId, GetAllStock,
    UpdateShopStockUnitPrice, AvailableItemsByShopResource,
    ItemDetailsResourceForShop, TransferSystemStock, GetItemsByShopId,
    BatchDetailsResource, AvailableBatchesResource, AvailableBatchesByShopResource,
    GetStockValueByShop, TotalStockValue, ShopStockByDate, GetBatchStock,
    GetItemStock, AddShopStock, BatchDetailsResourceForShop
)

from Server.Views.Inventoryviews import (
    AddInventory, GetAllInventory, InventoryResourceById, DistributeInventory,
    GetTransfer, ManualTransfer, StockDeletionResource, UpdateTransfer,
    GetTransferById, GetInventoryByBatch, DeleteShopStock
)

from Server.Views.Mabandafarmviews import (
    AddMabandaStock, AddMabandaExpense, AddMabandaPurchase, AddMabandaSale,
    MabandaSaleResource, MabandaPurchaseResource, MabandaStockResource,
    MabandaExpenseResource, TotalAmountPaidSalesMabanda, MabandaProfitLossAPI
)

from Server.Views.LiveStock import (
    GetStock, RegisterStock, CheckInStock, CheckoutStock, DeleteStock,
    AddStock, GetAllLiveStock, TransferStock, GetShopTransfers, AutoCheckoutStock
)

from Server.Views.Bankviews import (
    AddBank, BankResourceById
)

from Server.Views.Expenses import (
    AllExpenses, AddExpense, GetShopExpenses, ExpensesResources, TotalBalance
)

from Server.Views.Customersviews import (
    AddCustomer, GetAllCustomers, GetCustomerById, GetCustomersByShop
)

from Server.Views.Employeeviews import (
    AddNewemployee, GetAllemployees, Employeeresource, UpdateEmployeeShop,
    GetEmployeeLeaderboard
)

from Server.Views.employeeloanview import (
    AddEmployeeLoan, GetEmployeeLoan
)

from Server.Views.Sales import (
    AddSale, GetSales, GetSalesByShop, SalesResources, GetPaymentTotals,
    SalesBalanceResource, TotalBalanceSummary, 
    UpdateSalePayment, GetUnpaidSales, PaymentMethodsResource,
    CapturePaymentResource, CreditHistoryResource, GetSingleSaleByShop,
    SalesByEmployeeResource, GetSale, GetUnpaidSalesByClerk,
    TotalCashSalesByUser, CashSales, CashSalesByUser, GenerateSalesReport,ProductEarningsSummary,CategoryEarningsSummary, ItemsSoldSummary
)

from Server.Views.ManagerDashbordViews import (
    TotalAmountPaidExpenses, TotalAmountPaidSalesPerShop, CountEmployees,
    CountShops, TotalAmountPaidAllSales, TotalAmountPaidPerShop,
    TotalAmountPaidPurchases, StockAlert, TotalSalesByShop,
    TotalUnpaidAmountAllSales, TotalAmountPaidForMabanda,
    TotalAmountPaidPurchasesInventory, SalesSummary, TotalFinancialSummary,
    TotalUnpaidAmountPerClerk, TotalExpensesForMabanda,StockMovement,GetInventoryStock, MonthlyIncome,SendNotification
)

from Server.Views.Emailnotifications import (
    Report
)

from Server.Views.Accountingviews import (
    CreateChartOfAccounts, ChartOfAccountsList, SalesLedger, PurchasesLedger,GetItems,CreateItem
)

from Server.Views.AccountBalances import (
    PostBankAccount, DepositToAccount, BankAccountResource,MultipleToOneTransfer,
    GetAllBankAccounts, DailySalesDeposit, TotalBankBalance
)

from Server.Views.SpoiltStock import (
    AddSpoiltStock, SpoiltStockResource, ApproveSpoiltStock,RejectSpoiltStock, 
    GetPendingSpoiltStock, SpoiltStockHistory, AddSpoiltFromInventory, SpoiltValue
)

from Server.Views.StockItems import (
    PostStockItem, GetAllStockItems, StockItem
)

from Server.Views.CashDepositviews import (
    AddCashDeposit, CashDepositResource
)

from Server.Views.Saledepartmentviews import (
    SalesdepartmentSale, GetSalesdepartmentSales, GetSalesDepartmentSalesByUser,
    TotalAmountDepartmentSales, TotalAmountDepartmentSalesByUser, TopSalesUsers
)

from Server.Views.Meritpointsviews import (
    PostMeritPoint, GetAllMeripoints, MeritPointResource
)

from Server.Views.MeritandDemerit import (
    AssignMeritPoints, GetMeritLedger, GetEmployeeMeritLedger
)

from Server.Views.SupplierView import (
    AddSupplier, GetAllSuppliers, GetSingleSupplier,UpdateSupplier
)

from Server.Views.ShopstockviewsV2 import (
    AddShopStockV2, GetAllStockV2, GetBatchStockV2, GetItemsByShopIdV2,
    GetItemStockV2, GetStockValueByShopV2, GetShopStockByShopIdV2,
    GetShopStockV2, BatchDetailsResourceForShopV2, BatchDetailsResourceV2,
    AvailableBatchesByShopResourceV2, AvailableBatchesResourceV2,
    ShopStockByDateV2, AvailableItemsByShopResourceV2, ShopStockDeleteV2,
    TransferSystemStockV2, ItemDetailsResourceForShopV2, StockReturns, BrokenEggs, ApproveReturn, DeclineReturn, GetPendingReturns
)

from Server.Views.InventoryV2Views import (
    GetInventoryByBatchV2, DistributeInventoryV2, DeleteShopStockV2,
    GetTransferV2, GetTransferByIdV2, UpdateTransferV2, AddInventoryV2,ProcessInventoryPayment,
    GetAllInventoryV2, AllInventoryV2, InventoryResourceByIdV2, StockDeletionResourceV2,
    ManualTransferV2, ReceiveTransfer, DeclineTransfer, PendingTransfers,
    ProcessInventoryV2
)

from Server.Views.ShopstockviewsV2 import (
    AddShopStockV2, GetAllStockV2, GetBatchStockV2, GetItemsByShopIdV2, GetItemStockV2, GetStockValueByShopV2, GetShopStockByShopIdV2, GetShopStockV2, BatchDetailsResourceForShopV2, BatchDetailsResourceV2, AvailableBatchesByShopResourceV2, AvailableBatchesResourceV2, ShopStockByDateV2, AvailableItemsByShopResourceV2, ShopStockDeleteV2, ItemDetailsResourceForShopV2, StockReturns
)
from Server.Views.ExpenseCategoies import (
    PostExpenseCategory, GetAllExpenseCategories, ExpenseCategoryResource
)
from Server.Views.Shoptoshoptransferviews import (
    ShopToShopTransfer,  ConfirmTransfer, GetAllShopToShopTransfers, GetPendingShopToShopTransfers, DeclineTransfers
)
from Server.Views.StockReport import (
    SubmitStockReport, ResetShopReportStatus, GetStockReports, GetStockReportById, StockReconciliationList, StockReconciliationResource,
    GetReportedStock, StockReconciliationByShop, GetReconciliationItemsByShop, ReconciliationItemsByShop, InventoryCount
    
)

from Server.Views.Sasapaycodes import (
    ProcessCSV
)
from Server.Views.PushSubscription import  (
    PushSubscribe
)

from Server.Views.TaskManagerViews import (
    # Task Management
    CreateTask, TaskResource, GetTasks, CompleteTask, GetUserTasks,TaskProgressResource,TaskStatsResource,TaskCommentResource,CommentResource,TaskEvaluationResource
)
from Server.Views.CookedItemsView import  (
    AddCookedItems
)
from Server.Views.credirors import (
    CreateCreditor,CreditorsList,SingleCreditor,CreditorsByShop
)
from Server.Views.Permissions import (
    GetAllPermissions,GetUserPermissions,UpdateUserPermissions
)
from Server.Views.ShopTargets import (
    PostShopTarget,GetShopTargets,TargetResource
)

from Server.Views.LedgerViews import (

    SalesLedgerList,CreditSalesLedgerList,DistributionLedgerList,PurchaseLedgerInventoryList,BankTransfersLedgerList, ExpensesLedgerList, SpoiltStockLedgerList, CreateManualLedger, ManualLedgerList


)

from Server.Views.ClerkReportTime import (
    GetShopReports,GetShopReportStats,GetTodayShopReportStatus
)
from Server.Views.IncomeStatement import (IncomeStatement)
from Server.Views.Balancesheet import (BalanceSheet)

api_endpoint = Blueprint('auth',__name__,url_prefix='/api/diraja')
api = Api(api_endpoint)

# add all endpoints 

# Email reports
api.add_resource(Report, '/send-report')

api.add_resource(PushSubscribe ,'/subscribe')

# users endpoints 
api.add_resource(CountUsers, '/countusers')
api.add_resource(GetAllUsers,'/allusers')
api.add_resource(Addusers , '/newuser')
api.add_resource(UsersResourceById, '/user/<int:users_id>')
api.add_resource(UserLogin, '/login')
api.add_resource(PostShopReport, "/shop-reports")


# shops endpoints 
api.add_resource(AddShops, '/newshop')
api.add_resource(ShopsResourceById, '/shop/<int:shops_id>')
api.add_resource(GetAllShops, '/allshops')
api.add_resource(GetActiveShops, '/activeshops')

#stock endpoints
api.add_resource(GetShopStock, '/shopstock')
api.add_resource(GetShopStockByShopId, '/shopstock/shop/<int:shop_id>')  
api.add_resource(ShopStockDelete, '/shops/<int:shop_id>/inventory/<int:inventory_id>/delete')
api.add_resource(BatchDetailsResource, '/batch-details')
api.add_resource(BatchDetailsResourceForShop, '/shop-batchdetails')
api.add_resource(AvailableBatchesResource, '/batches/available')
api.add_resource(AvailableBatchesByShopResource, '/batches/available-by-shop')
api.add_resource(GetAllStock, '/allstock')
api.add_resource(GetStockValueByShop, '/shop/<int:shop_id>/stock-value')
api.add_resource(TotalStockValue, '/shopstock/value')
api.add_resource(UpdateShopStockUnitPrice, '/shopstock/<int:stock_id>/update-unitprice')
# api.add_resource(TransferSystemStock, "/transfer-system-stock")
api.add_resource(GetBatchStock, '/batch-stock-level')
api.add_resource(GetItemStock, '/item-stock-level')
api.add_resource(ShopStockByDate, '/shopstock/bydate')
api.add_resource(AvailableItemsByShopResource, '/items/available-by-shop')
api.add_resource(ItemDetailsResourceForShop, '/shop-itemdetails')
api.add_resource(AddShopStock, '/addstock')
api.add_resource(GetItemsByShopId, '/items/<int:shop_id>')

#Employess Routes
api.add_resource(AddNewemployee, '/newemployee')
api.add_resource(GetAllemployees,'/allemployees')
api.add_resource(Employeeresource, '/employee/<int:employee_id>')
api.add_resource(UpdateEmployeeShop, '/update-shop/<int:employee_id>')
api.add_resource(AddEmployeeLoan,'/newloan')
api.add_resource(GetEmployeeLeaderboard, '/leaderboard/employee')
api.add_resource(GetEmployeeLoan,'/employee/loan/<int:employee_id>')

# inventory endpoints 
api.add_resource(AddInventory, '/newinventory')
api.add_resource(GetAllInventory,'/allinventories')
api.add_resource(InventoryResourceById, '/inventory/<int:inventory_id>')
api.add_resource(DeleteShopStock, '/deleteshopstock/<int:shop_stock_id>')
api.add_resource(GetInventoryByBatch, '/inventory-by-batch')

# expenses endpoint 
api.add_resource(AddExpense,'/newexpense')
api.add_resource(AllExpenses, '/allexpenses')
api.add_resource(GetShopExpenses, '/expense/shop/<int:shop_id>')
api.add_resource(ExpensesResources,'/expense/<int:expense_id>')
api.add_resource(TotalBalance, '/accountsreceivable')

# banks endpoint
api.add_resource(AddBank, '/newbank')
api.add_resource(BankResourceById, '/bank/<int:bank_id>')

#Customers endpoints
api.add_resource(AddCustomer, '/newcustomer')  
api.add_resource(GetAllCustomers, '/allcustomers')  
api.add_resource(GetCustomersByShop, '/customers/<shop_id>')
api.add_resource(GetCustomerById, '/customer/<int:customer_id>')

#Sales 
api.add_resource(AddSale, '/newsale')
api.add_resource(GetSales, '/allsales')
api.add_resource(GetSalesByShop,'/sales/shop/<int:shop_id>')
api.add_resource(SalesResources,'/sale/<int:sales_id>')
api.add_resource(GetPaymentTotals, '/get_payment_totals')
api.add_resource(SalesBalanceResource, '/sales/totalsalesbalance')
api.add_resource(TotalBalanceSummary, '/accountspayable')
api.add_resource(GetUnpaidSales, '/unpaidsales')
api.add_resource(SalesByEmployeeResource, '/sales/<string:username>')
api.add_resource(UpdateSalePayment, '/sale/<int:sale_id>/payment')
api.add_resource(PaymentMethodsResource, "/sales/<int:sale_id>/payment_methods")
api.add_resource(CapturePaymentResource, "/sales/<int:sale_id>/capture-payment")
api.add_resource(CreditHistoryResource, "/credit-history")
api.add_resource(GetSingleSaleByShop, "/sale/<int:shop_id>/<int:sales_id>")
api.add_resource(GetUnpaidSalesByClerk, "/unpaidsales/clerk") 
api.add_resource(ItemsSoldSummary, '/sold-items-summary', '/sold-items-summary/<int:shop_id>')
api.add_resource(ProductEarningsSummary, '/shops/<int:shop_id>/product-earnings', '/product-earnings')
api.add_resource(CategoryEarningsSummary, "/category-earnings-summary", "/category-earnings-summary/<int:shop_id>")


#Distribution
api.add_resource(DistributeInventory,'/transfer')
api.add_resource(GetTransfer,'/alltransfers')
api.add_resource(UpdateTransfer, "/updatetransfer/<int:transfer_id>")
api.add_resource(ManualTransfer,'/manualtransfer')
api.add_resource(GetTransferById, '/singletransfer/<int:transfer_id>')

#Live stock
api.add_resource(GetStock,"/get-stock/<int:shop_id>")
api.add_resource(RegisterStock , '/registerstock')
api.add_resource(CheckInStock, '/stockcheckin')
api.add_resource(DeleteStock, "/delete-stock/<int:stock_id>" )
api.add_resource(AddStock, "/addstock")
api.add_resource(CheckoutStock, "/checkout")
api.add_resource(GetAllLiveStock , "/all-shop-stocks")
api.add_resource(TransferStock , "/transfer-shop-stock")
api.add_resource(GetShopTransfers, '/allshoptransfers' )
api.add_resource(AutoCheckoutStock, "/auto-checkout")

#manager dashbord
api.add_resource(CountShops, '/totalshops')
api.add_resource(CountEmployees,'/totalemployees')
api.add_resource(TotalAmountPaidExpenses,'/totalexpenses')
api.add_resource(TotalAmountPaidSalesPerShop,'/totalsales')
api.add_resource(TotalAmountPaidAllSales,"/allshopstotal")
api.add_resource(TotalAmountPaidPurchases,"/totalpurchases")
api.add_resource(TotalAmountPaidPurchasesInventory,"/Invetory-purchase")
api.add_resource(StockAlert,"/checkstock")
api.add_resource(TotalUnpaidAmountAllSales,"/allunpaidtotal")
api.add_resource(TotalAmountPaidForMabanda,'/totalmabandasales')
api.add_resource(TotalExpensesForMabanda,'/totalmabandaexpenses')
api.add_resource(SalesSummary,'/Sale-Summery')
api.add_resource(TotalFinancialSummary,'/summery')
api.add_resource(TotalUnpaidAmountPerClerk, "/unpaidsales/totalperclerk")
api.add_resource(TotalAmountPaidPerShop,"/totalsalespershop")
api.add_resource(TotalSalesByShop,"/totalsalesbyshop/<int:shop_id>")
api.add_resource(StockMovement, '/stock-movement')
api.add_resource(GetInventoryStock, '/inventory-stock-level')
api.add_resource(MonthlyIncome, '/monthly-analytics')
api.add_resource(SendNotification, "/send_notification")

# Mabanda shop 
api.add_resource(AddMabandaSale,'/newmabandasale')
api.add_resource(AddMabandaExpense,'/newmabandaexpense')
api.add_resource(AddMabandaPurchase,'/newmabandapurchase')
api.add_resource(AddMabandaStock,'/newmabandastock')
api.add_resource(MabandaSaleResource,'/getmabandasale')
api.add_resource(MabandaPurchaseResource,'/getmabandapurchase')
api.add_resource(MabandaStockResource,'/getmabandastock')
api.add_resource(MabandaExpenseResource,'/getmabandaexpense')
api.add_resource(TotalAmountPaidSalesMabanda,'/totalsalesmabanda')
api.add_resource(MabandaProfitLossAPI, '/mabandap&l')

#Accounting 
# api.add_resource(CreateAccount, '/add-account')
# api.add_resource(AccountTypeListResource, '/account-types/all')
# api.add_resource(AccountTypeResource, '/account-types/<int:id>')
api.add_resource(CreateChartOfAccounts, '/add-chart-of-accounts')
api.add_resource(ChartOfAccountsList, '/chart-of-accounts')
# api.add_resource(CreateItemAccount, '/itemaccounts')
# api.add_resource(GetAllItemAccounts, '/itemaccounts/all')
api.add_resource(SalesLedger, '/sale-ledger')
api.add_resource(PurchasesLedger , '/purchases-ledger')
api.add_resource(CreateItem,'/create-items')
api.add_resource(GetItems, '/created-items-list')

#Account Ballance 
api.add_resource(PostBankAccount, '/bankaccount')
api.add_resource(GetAllBankAccounts, '/all-acounts')
api.add_resource(DailySalesDeposit, '/sales/daily-deposit', '/sales/daily-deposit/<string:date_str>')
api.add_resource(BankAccountResource, '/bankaccount/<int:account_id>/deposit')
api.add_resource(TotalBankBalance, '/total-balance')
api.add_resource(MultipleToOneTransfer,"/bulk-transfer")

#Spoiltstock
api.add_resource(AddSpoiltStock, '/newspoilt')
api.add_resource(SpoiltStockResource, '/allspoilt')
api.add_resource(ApproveSpoiltStock, '/spoilt/<int:record_id>/approve')
api.add_resource(RejectSpoiltStock, '/spoilt/<int:record_id>/reject')
api.add_resource(GetPendingSpoiltStock, '/spoilt/pending')
api.add_resource(SpoiltStockHistory, '/spoilt/history')
api.add_resource(AddSpoiltFromInventory, "/spoilt/inventory")
api.add_resource(SpoiltValue, "/spoilt-value")

#stockItems 
api.add_resource(PostStockItem, '/add-stock-items')
api.add_resource(GetAllStockItems, '/stockitems')
api.add_resource(StockItem, '/stockitems/<int:item_id>')

#Cash sales
api.add_resource(CashSales, '/sales/cash/shops', '/sales/cash/sale/<int:sale_id>')
api.add_resource(CashSalesByUser, '/sales/cash/user/<int:user_id>')
api.add_resource(TotalCashSalesByUser, '/cashsaleperuser/<string:username>/<int:shop_id>')

#Cash Deposits
api.add_resource(AddCashDeposit, '/cashdeposits/add')
api.add_resource(CashDepositResource, '/cashdeposits', '/cashdeposits/<int:deposit_id>')

#reports 
api.add_resource(GenerateSalesReport, '/generate-sales-report')

#Sales Department
api.add_resource(SalesdepartmentSale, '/salesdepartmentnew')
api.add_resource(GetSalesdepartmentSales, '/allsalesdepartmentsales')
api.add_resource(GetSalesDepartmentSalesByUser, '/salesdepartmentsales/<int:user_id>')
api.add_resource(TotalAmountDepartmentSales,"/salesdepartmenttotal")
api.add_resource(TotalAmountDepartmentSalesByUser,"/salesdepartmenttotal/<int:user_id>")
api.add_resource(TopSalesUsers,'/promo-sales-rank')

#Merit points
api.add_resource(PostMeritPoint, '/newmeritpoint')
api.add_resource(GetAllMeripoints, '/allmeritpoints')
api.add_resource(MeritPointResource, '/merit-points/<int:id>')
api.add_resource(AssignMeritPoints, '/employee/<int:employee_id>/assign-merit')
api.add_resource(GetMeritLedger, '/meritledger')
api.add_resource(GetEmployeeMeritLedger, '/employees-merit/<int:user_id>')



#Suppliers endpoints 
api.add_resource(AddSupplier , '/creat-supplier')
api.add_resource(GetAllSuppliers,'/all-suppliers' )
api.add_resource(GetSingleSupplier, '/suppliers/<int:supplier_id>')
api.add_resource(UpdateSupplier, '/suppliers/update/<int:supplier_id>')

#stockv2 endpoints
# api.add_resource(GetShopStockV2, '/shopstockv2')
# api.add_resource(GetShopStockByShopIdV2, '/shopstockv2/shop/<int:shop_id>')  
# api.add_resource(ShopStockDeleteV2, '/shops/<int:shop_id>/inventory/<int:inventory_id>/deletev2')
# api.add_resource(BatchDetailsResourceV2, '/batch-detailsv2')
# api.add_resource(BatchDetailsResourceForShopV2, '/shop-batchdetailsv2')
# api.add_resource(AvailableBatchesResourceV2, '/batches/availablev2')
# api.add_resource(AvailableItemsByShopResourceV2, '/batches/available-by-shopv2')
# api.add_resource(GetAllStockV2, '/allstockv2')
#Get stock
#Get stock by shopid
# api.add_resource(GetShopStockByShopIdV2, '/shopstockv2/shop/<int:shop_id>')  
# api.add_resource(ShopStockDeleteV2, '/shops/<int:shop_id>/inventory/<int:inventory_id>/deletev2')
# api.add_resource(BatchDetailsResourceV2, '/batch-detailsv2')
# api.add_resource(BatchDetailsResourceForShopV2, '/shop-batchdetailsv2')
# api.add_resource(AvailableBatchesResourceV2, '/batches/availablev2')
# api.add_resource(AvailableItemsByShopResourceV2, '/batches/available-by-shopv2')
# api.add_resource(GetAllStockV2, '/allstockv2')

# Inventory V2 endpoints
api.add_resource(AddInventoryV2, '/v2/newinventory')
api.add_resource(ProcessInventoryPayment, '/inventory/payment') 
api.add_resource(GetAllInventoryV2, '/new/allinventories')
api.add_resource(AllInventoryV2, '/v2/allinventories')
api.add_resource(InventoryResourceByIdV2, '/v2/inventory/<int:inventoryV2_id>')
api.add_resource(DeleteShopStockV2, '/v2/deleteshopstock/<int:stockv2_id>')
api.add_resource(GetInventoryByBatchV2, '/v2/inventory-by-batch')
api.add_resource(DistributeInventoryV2, '/v2/distribute-inventory')
api.add_resource(ProcessInventoryV2, '/create-parts')
api.add_resource(GetTransferV2, '/v2/transfers')
api.add_resource(GetTransferByIdV2, '/v2/transfer/<int:transferV2_id>')
api.add_resource(UpdateTransferV2, '/v2/transfer/<int:transferV2_id>')
api.add_resource(StockDeletionResourceV2, '/v2/stock/<int:stockV2_id>')
api.add_resource(ManualTransferV2, '/v2/manual-transfer')
api.add_resource(ReceiveTransfer, '/transfers/<int:transfer_id>/receive')
api.add_resource(DeclineTransfer, '/transfers/<int:transfer_id>/decline')
api.add_resource(PendingTransfers, '/transfers/pending')




#stockv2 endpoints
#Get stock
api.add_resource(GetShopStockV2, '/shopstockv2')
#Get stock by shopid
api.add_resource(GetShopStockByShopIdV2, '/shopstockv2/shop/<int:shop_id>')  
api.add_resource(ShopStockDeleteV2, '/shops/<int:shop_id>/stock/delete')
api.add_resource(BatchDetailsResourceV2, '/batch-detailsv2')
api.add_resource(BatchDetailsResourceForShopV2, '/shop-batchdetailsv2')
api.add_resource(AvailableBatchesResourceV2, '/batches/availablev2')
api.add_resource(AvailableItemsByShopResourceV2, '/batches/available-by-shopv2')
api.add_resource(GetAllStockV2, '/allstockv2')
api.add_resource(ItemDetailsResourceForShopV2, '/shop-itemdetailsv2')
api.add_resource(TransferSystemStockV2, "/transfer-system-stock")
api.add_resource(StockReturns, "/stockreturns")
api.add_resource(BrokenEggs, "/shops/<int:shop_id>/stock/broken-eggs")

api.add_resource(AddCookedItems, "/shops/<int:shop_id>/stock/cooked")

api.add_resource(ApproveReturn, '/returns/<int:return_id>/approve')
api.add_resource(DeclineReturn, '/returns/<int:return_id>/decline')
api.add_resource(GetPendingReturns, '/returns/pending')


#Shoptoshop transfer
api.add_resource(ShopToShopTransfer, '/transfer-stock')
api.add_resource(GetAllShopToShopTransfers, '/allstocktransfers')
api.add_resource(ConfirmTransfer, '/confirm-transfer/<int:transfer_id>')
api.add_resource(DeclineTransfers, '/decline-transfer/<int:transfer_id>')
api.add_resource(GetPendingShopToShopTransfers, '/pending-transfers')
# api.add_resource(TransferNotifications, "/transfer-notifications")
# api.add_resource(ShopToShopTransferList, "/shoptoshoptransfers")
# api.add_resource(AcknowledgeNotification, '/acknowledge-notification/<int:transfer_id>')



#Expensecategories
api.add_resource(PostExpenseCategory, '/add-expense-category')
api.add_resource(GetAllExpenseCategories, '/expensecategories')
api.add_resource(ExpenseCategoryResource, '/expensecategories/<int:category_id>')



#StockReport 
api.add_resource(SubmitStockReport, '/report-stock')
api.add_resource(InventoryCount, '/inventory-count')
api.add_resource(ResetShopReportStatus, '/reset-report')
api.add_resource(GetStockReports, '/stock-reports')
api.add_resource(GetStockReportById, '/stock-reports/<int:report_id>')
api.add_resource(StockReconciliationList, '/stock-reconciliation')
api.add_resource(StockReconciliationByShop, '/stock-reconciliations')
api.add_resource(GetReconciliationItemsByShop, '/reconciliation-stock-level')
api.add_resource(ReconciliationItemsByShop, '/reportedstock')
api.add_resource(StockReconciliationResource, '/stock-reconciliation/<int:reconciliation_id>')
api.add_resource(GetReportedStock, '/reconciliation-level')



api.add_resource(ProcessCSV, '/process-csv')


#TaskManager
# Task Management Routes
api.add_resource(CreateTask, "/newtask")
api.add_resource(TaskResource, "/tasks/<int:task_id>")
api.add_resource(GetTasks, "/alltasks")
api.add_resource(GetUserTasks, "/mytasks/<int:user_id>")
api.add_resource(CompleteTask, '/<int:task_id>/complete')
api.add_resource(TaskProgressResource, "/tasks/<int:task_id>/progress")
api.add_resource(TaskStatsResource, "/tasks/stats")
api.add_resource(TaskCommentResource, "/tasks/<int:task_id>/comments")    
api.add_resource(CommentResource, "/comments/<int:comment_id>")           

api.add_resource(TaskEvaluationResource, "/tasks/<int:task_id>/evaluation") 

#creditors
api.add_resource(CreateCreditor, '/add-creditors')
api.add_resource(CreditorsList, '/creditors')
api.add_resource(SingleCreditor, '/creditors/<int:creditor_id>')
api.add_resource(CreditorsByShop, '/creditors/shop/<int:shop_id>')



#permissions 
api.add_resource(GetAllPermissions, "/permissions/all")
api.add_resource(GetUserPermissions, "/permissions/user/<int:user_id>")
api.add_resource(UpdateUserPermissions, "/permissions/user/<int:user_id>")



#ShopTargets 
api.add_resource(TargetResource, "/shop-targets/<int:target_id>") 
api.add_resource(PostShopTarget, "/add-target")
api.add_resource(GetShopTargets, "/targets")

#LEdgers 
api.add_resource(SalesLedgerList, "/accounting/sales-ledger")
api.add_resource(CreateManualLedger, "/create-manual-ledger")
api.add_resource(CreditSalesLedgerList,"/accounting/credit-sales-ledger")
api.add_resource(DistributionLedgerList, '/accounting/distribution-ledger')
api.add_resource(PurchaseLedgerInventoryList, '/accounting/purchase-ledger-inventory')
api.add_resource(BankTransfersLedgerList, '/accounting/bank-transfers-ledger')
api.add_resource(SpoiltStockLedgerList, "/accounting/spoilt-ledger")
api.add_resource(ExpensesLedgerList, "/accounting/expenses-ledger")
api.add_resource(ManualLedgerList,"/accounting/manual-ledger")


# clerkShopReportTime
api.add_resource(GetShopReports, '/shop-reports')
api.add_resource(GetTodayShopReportStatus, '/shop-reports/today-status')
api.add_resource(GetShopReportStats, '/shop-reports/stats')


#income statement 
api.add_resource(IncomeStatement,'/income-statement')

#balance sheet
api.add_resource(BalanceSheet,'/balance-sheet')