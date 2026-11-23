package com.cashbook.app.ui.nav

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ReceiptLong
import androidx.compose.material.icons.filled.AddCircle
import androidx.compose.material.icons.filled.Assessment
import androidx.compose.material.icons.filled.Dashboard
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.ListItem
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.runtime.remember
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import androidx.navigation.NavGraph.Companion.findStartDestination
import androidx.navigation.NavHostController
import androidx.navigation.NavType
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.currentBackStackEntryAsState
import androidx.navigation.compose.rememberNavController
import androidx.navigation.navArgument
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.cashbook.app.R
import com.cashbook.app.ui.AppViewModel
import com.cashbook.app.ui.components.TypeAvatar
import com.cashbook.app.ui.components.typeIcon
import com.cashbook.app.ui.dashboard.DashboardScreen
import com.cashbook.app.ui.manage.AccountEditScreen
import com.cashbook.app.ui.manage.BudgetsScreen
import com.cashbook.app.ui.invoices.InvoiceDetailScreen
import com.cashbook.app.ui.invoices.InvoiceEditScreen
import com.cashbook.app.ui.invoices.InvoicesScreen
import com.cashbook.app.ui.invoices.RecordPaymentScreen
import com.cashbook.app.ui.recurring.RecurringEditScreen
import com.cashbook.app.ui.recurring.RecurringListScreen
import com.cashbook.app.ui.manage.AccountsScreen
import com.cashbook.app.ui.manage.CashbookEditScreen
import com.cashbook.app.ui.manage.CashbooksScreen
import com.cashbook.app.ui.manage.CategoriesScreen
import com.cashbook.app.ui.manage.CategoryEditScreen
import com.cashbook.app.ui.manage.PartiesScreen
import com.cashbook.app.ui.manage.PartyDetailScreen
import com.cashbook.app.ui.manage.PartyEditScreen
import com.cashbook.app.ui.reports.ReportViewScreen
import com.cashbook.app.ui.reports.ReportsScreen
import com.cashbook.app.ui.settings.AboutScreen
import com.cashbook.app.ui.settings.BackupScreen
import com.cashbook.app.ui.settings.GeneralSettingsScreen
import com.cashbook.app.ui.settings.GuideScreen
import com.cashbook.app.ui.settings.PrivacyScreen
import com.cashbook.app.ui.settings.RecycleBinScreen
import com.cashbook.app.ui.settings.SecuritySettingsScreen
import com.cashbook.app.ui.settings.SettingsScreen
import com.cashbook.app.ui.transactions.TransactionDetailScreen
import com.cashbook.app.ui.transactions.TransactionFormScreen
import com.cashbook.app.ui.transactions.TransactionListScreen
import com.cashbook.core.TxnType

object Routes {
    const val DASHBOARD = "dashboard"
    const val TRANSACTIONS = "transactions"
    const val REPORTS = "reports"
    const val SETTINGS = "settings"
    fun newTxn(type: TxnType) = "txn/new/${type.name}"
    fun editTxn(id: Long) = "txn/edit/$id"
    fun duplicateTxn(id: Long) = "txn/duplicate/$id"
    fun txn(id: Long) = "txn/view/$id"
    fun report(type: String) = "report/$type"
    const val CASHBOOKS = "cashbooks"
    fun cashbook(id: Long) = "cashbook/$id"
    fun accounts(cashbookId: Long) = "accounts/$cashbookId"
    fun account(cashbookId: Long, id: Long) = "account/$cashbookId/$id"
    const val CATEGORIES = "categories"
    fun category(id: Long, kind: String = "EXPENSE") = "category/$id/$kind"
    const val PARTIES = "parties"
    fun party(id: Long) = "party/$id"
    fun partyDetail(id: Long) = "party_detail/$id"
    const val GENERAL = "settings_general"
    const val SECURITY = "settings_security"
    const val BACKUP = "backup"
    const val RECYCLE = "recycle"
    const val GUIDE = "guide"
    const val PRIVACY = "privacy"
    const val ABOUT = "about"
    const val RECURRING = "recurring"
    fun recurringEdit(id: Long, fromTxn: Long = 0) = "recurring/$id/$fromTxn"
    const val BUDGETS = "budgets"
    const val INVOICES = "invoices"
    fun invoiceEdit(id: Long, kind: String = "SALE", partyId: Long = 0) = "invoice_edit/$id/$kind/$partyId"
    fun invoice(id: Long) = "invoice/$id"
    fun recordPayment(id: Long) = "invoice_pay/$id"
    const val BUSINESS = "business_profile"
}

private data class Tab(val route: String, val label: Int, val icon: ImageVector)

/** Navigates to a top-level tab, keeping each tab's state. */
fun NavHostController.openTab(route: String) = navigate(route) {
    popUpTo(graph.findStartDestination().id) { saveState = true }
    launchSingleTop = true
    restoreState = true
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun MainNav(vm: AppViewModel) {
    val nav = rememberNavController()
    var addSheet by rememberSaveable { mutableStateOf(false) }
    val tabs = listOf(
        Tab(Routes.DASHBOARD, R.string.nav_dashboard, Icons.Filled.Dashboard),
        Tab(Routes.TRANSACTIONS, R.string.nav_transactions, Icons.AutoMirrored.Filled.ReceiptLong),
        Tab("add", R.string.nav_add, Icons.Filled.AddCircle),
        Tab(Routes.REPORTS, R.string.nav_reports, Icons.Filled.Assessment),
        Tab(Routes.SETTINGS, R.string.nav_settings, Icons.Filled.Settings),
    )
    val entry by nav.currentBackStackEntryAsState()
    val current = entry?.destination?.route
    val showBar = current in setOf(Routes.DASHBOARD, Routes.TRANSACTIONS, Routes.REPORTS, Routes.SETTINGS)

    val openRequest by vm.openRequest.collectAsStateWithLifecycle()
    LaunchedEffect(openRequest) {
        val target = openRequest ?: return@LaunchedEffect
        vm.consumeOpen()
        when {
            target == "backup" -> nav.navigate(Routes.BACKUP)
            target == "invoices" -> nav.navigate(Routes.INVOICES)
            target == "budgets" -> nav.navigate(Routes.BUDGETS)
            target == "dashboard" -> nav.openTab(Routes.DASHBOARD)
            target.startsWith("add_") -> runCatching { TxnType.valueOf(target.removePrefix("add_")) }.getOrNull()?.let { nav.navigate(Routes.newTxn(it)) }
        }
    }

    // App-wide confirmations ("Saved", "Moved to recycle bin", errors) from AppViewModel.toast().
    val snackbar = remember { SnackbarHostState() }
    LaunchedEffect(Unit) { vm.messages.collect { snackbar.showSnackbar(it) } }

    Scaffold(
        snackbarHost = { SnackbarHost(snackbar) },
        bottomBar = {
            if (showBar) NavigationBar {
                tabs.forEach { t ->
                    NavigationBarItem(
                        selected = current == t.route,
                        onClick = { if (t.route == "add") addSheet = true else nav.openTab(t.route) },
                        icon = { Icon(t.icon, null, modifier = if (t.route == "add") Modifier.size(32.dp) else Modifier) },
                        label = { Text(stringResource(t.label), maxLines = 1, style = MaterialTheme.typography.labelSmall, softWrap = false) },
                    )
                }
            }
        },
    ) { pad ->
        NavHost(nav, startDestination = Routes.DASHBOARD, modifier = Modifier.padding(bottom = pad.calculateBottomPadding())) {
            composable(Routes.DASHBOARD) { DashboardScreen(vm, nav) }
            composable(Routes.TRANSACTIONS) { TransactionListScreen(vm, nav) }
            composable(Routes.REPORTS) { ReportsScreen(vm, nav) }
            composable(Routes.SETTINGS) { SettingsScreen(vm, nav) }
            composable("txn/new/{type}") { e ->
                TransactionFormScreen(vm, nav, type = TxnType.valueOf(e.arguments?.getString("type") ?: "EXPENSE"), editId = 0, duplicateId = 0)
            }
            composable("txn/edit/{id}", listOf(navArgument("id") { type = NavType.LongType })) { e ->
                TransactionFormScreen(vm, nav, type = null, editId = e.arguments!!.getLong("id"), duplicateId = 0)
            }
            composable("txn/duplicate/{id}", listOf(navArgument("id") { type = NavType.LongType })) { e ->
                TransactionFormScreen(vm, nav, type = null, editId = 0, duplicateId = e.arguments!!.getLong("id"))
            }
            composable("txn/view/{id}", listOf(navArgument("id") { type = NavType.LongType })) { e ->
                TransactionDetailScreen(vm, nav, e.arguments!!.getLong("id"))
            }
            composable("report/{type}") { e -> ReportViewScreen(vm, nav, e.arguments?.getString("type") ?: "CUSTOM") }
            composable(Routes.CASHBOOKS) { CashbooksScreen(vm, nav) }
            composable("cashbook/{id}", listOf(navArgument("id") { type = NavType.LongType })) { e -> CashbookEditScreen(vm, nav, e.arguments!!.getLong("id")) }
            composable("accounts/{cb}", listOf(navArgument("cb") { type = NavType.LongType })) { e -> AccountsScreen(vm, nav, e.arguments!!.getLong("cb")) }
            composable("account/{cb}/{id}", listOf(navArgument("cb") { type = NavType.LongType }, navArgument("id") { type = NavType.LongType })) { e ->
                AccountEditScreen(vm, nav, e.arguments!!.getLong("cb"), e.arguments!!.getLong("id"))
            }
            composable(Routes.CATEGORIES) { CategoriesScreen(vm, nav) }
            composable("category/{id}/{kind}", listOf(navArgument("id") { type = NavType.LongType })) { e ->
                CategoryEditScreen(vm, nav, e.arguments!!.getLong("id"), e.arguments?.getString("kind") ?: "EXPENSE")
            }
            composable(Routes.PARTIES) { PartiesScreen(vm, nav) }
            composable("party/{id}", listOf(navArgument("id") { type = NavType.LongType })) { e -> PartyEditScreen(vm, nav, e.arguments!!.getLong("id")) }
            composable("party_detail/{id}", listOf(navArgument("id") { type = NavType.LongType })) { e -> PartyDetailScreen(vm, nav, e.arguments!!.getLong("id")) }
            composable(Routes.GENERAL) { GeneralSettingsScreen(vm, nav) }
            composable(Routes.SECURITY) { SecuritySettingsScreen(vm, nav) }
            composable(Routes.BACKUP) { BackupScreen(vm, nav) }
            composable(Routes.RECYCLE) { RecycleBinScreen(vm, nav) }
            composable(Routes.GUIDE) { GuideScreen(nav) }
            composable(Routes.PRIVACY) { PrivacyScreen(nav) }
            composable(Routes.ABOUT) { AboutScreen(nav) }
            composable(Routes.RECURRING) { RecurringListScreen(vm, nav) }
            composable("recurring/{id}/{from}", listOf(navArgument("id") { type = NavType.LongType }, navArgument("from") { type = NavType.LongType })) { e ->
                RecurringEditScreen(vm, nav, e.arguments!!.getLong("id"), e.arguments!!.getLong("from"))
            }
            composable(Routes.BUDGETS) { BudgetsScreen(vm, nav) }
            composable(Routes.INVOICES) { InvoicesScreen(vm, nav) }
            composable(Routes.BUSINESS) { com.cashbook.app.ui.settings.BusinessProfileScreen(vm, nav) }
            composable("invoice_pay/{id}", listOf(navArgument("id") { type = NavType.LongType })) { e -> RecordPaymentScreen(vm, nav, e.arguments!!.getLong("id")) }
            composable("invoice/{id}", listOf(navArgument("id") { type = NavType.LongType })) { e -> InvoiceDetailScreen(vm, nav, e.arguments!!.getLong("id")) }
            composable("invoice_edit/{id}/{kind}/{party}", listOf(navArgument("id") { type = NavType.LongType }, navArgument("party") { type = NavType.LongType })) { e ->
                InvoiceEditScreen(vm, nav, e.arguments!!.getLong("id"), e.arguments?.getString("kind") ?: "SALE", e.arguments!!.getLong("party"))
            }
        }
    }

    if (addSheet) {
        ModalBottomSheet(onDismissRequest = { addSheet = false }) {
            Column(Modifier.fillMaxWidth().padding(bottom = 24.dp)) {
                Text(stringResource(R.string.add_entry), style = MaterialTheme.typography.titleMedium, modifier = Modifier.padding(horizontal = 24.dp, vertical = 8.dp))
                listOf(
                    Triple(TxnType.INCOME, R.string.add_income, R.string.add_income_desc),
                    Triple(TxnType.EXPENSE, R.string.add_expense, R.string.add_expense_desc),
                    Triple(TxnType.TRANSFER, R.string.add_transfer, R.string.add_transfer_desc),
                ).forEach { (type, title, desc) ->
                    ListItem(
                        headlineContent = { Text(stringResource(title)) },
                        supportingContent = { Text(stringResource(desc)) },
                        leadingContent = { TypeAvatar(type, typeIcon(type)) },
                        modifier = Modifier.clickable { addSheet = false; nav.navigate(Routes.newTxn(type)) }.padding(horizontal = 8.dp),
                    )
                }
                Spacer(Modifier.size(8.dp))
            }
        }
    }
}
