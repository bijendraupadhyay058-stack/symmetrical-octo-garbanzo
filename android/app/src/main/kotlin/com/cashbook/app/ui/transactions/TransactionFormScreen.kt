package com.cashbook.app.ui.transactions

import android.net.Uri
import androidx.activity.compose.BackHandler
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.PickVisualMediaRequest
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.AccountBalanceWallet
import androidx.compose.material.icons.filled.Category
import androidx.compose.material.icons.filled.Description
import androidx.compose.material.icons.filled.Person
import androidx.compose.material.icons.filled.PhotoCamera
import androidx.compose.material.icons.filled.PhotoLibrary
import androidx.compose.material.icons.filled.Warning
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.SegmentedButton
import androidx.compose.material3.SegmentedButtonDefaults
import androidx.compose.material3.SingleChoiceSegmentedButtonRow
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.input.KeyboardCapitalization
import androidx.compose.ui.unit.dp
import androidx.core.content.FileProvider
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.lifecycle.createSavedStateHandle
import androidx.navigation.NavHostController
import com.cashbook.app.R
import com.cashbook.app.data.AttachmentStore
import com.cashbook.app.data.db.PartyEntity
import com.cashbook.app.export.Exporter
import com.cashbook.app.ui.AppViewModel
import com.cashbook.app.ui.components.AppScaffold
import com.cashbook.app.ui.components.AttachmentItem
import com.cashbook.app.ui.components.AttachmentUi
import com.cashbook.app.ui.components.DateField
import com.cashbook.app.ui.components.DropdownField
import com.cashbook.app.ui.components.InlineChoice
import com.cashbook.app.ui.components.InfoBanner
import com.cashbook.app.ui.components.LocalUiFormat
import com.cashbook.app.ui.components.MoneyField
import com.cashbook.app.ui.components.PickItem
import com.cashbook.app.ui.components.PickerField
import com.cashbook.app.ui.components.SearchPickerSheet
import com.cashbook.app.ui.components.SectionCard
import com.cashbook.app.ui.components.accountIcon
import com.cashbook.app.ui.components.accountTypeLabel
import com.cashbook.app.ui.components.categoryIcon
import com.cashbook.app.ui.components.paymentModeLabel
import com.cashbook.app.ui.components.partyTypeLabel
import com.cashbook.app.ui.components.txnTypeLabel
import com.cashbook.app.ui.components.typeIcon
import com.cashbook.app.ui.theme.LocalFinanceColors
import com.cashbook.core.CategoryKind
import com.cashbook.core.PartyType
import com.cashbook.core.PaymentMode
import com.cashbook.core.TxnType
import kotlinx.coroutines.launch
import java.io.File
import java.time.LocalDate

@Composable
fun TransactionFormScreen(vm: AppViewModel, nav: NavHostController, type: TxnType?, editId: Long, duplicateId: Long) {
    val deps = vm.deps ?: return
    val form: TxnFormViewModel = viewModel(key = "txn-form-$type-$editId-$duplicateId") {
        TxnFormViewModel(createSavedStateHandle(), deps, type, editId, duplicateId)
    }
    val snap by vm.snapshot.collectAsStateWithLifecycle()
    val settings by vm.settings.collectAsStateWithLifecycle()
    val s = settings ?: return
    val ctx = LocalContext.current
    val f = LocalUiFormat.current
    val fc = LocalFinanceColors.current
    val snackbar = remember { SnackbarHostState() }
    val scope = rememberCoroutineScope()
    val scroll = rememberScrollState()

    LaunchedEffect(snap.loaded) { form.initialize(snap, s); form.loadExistingIfNeeded() }

    var picker by rememberSaveable { mutableStateOf<String?>(null) } // category | party | account | to
    var newCategory by rememberSaveable { mutableStateOf<String?>(null) }
    var newParty by rememberSaveable { mutableStateOf<String?>(null) }
    var replacing by rememberSaveable { mutableStateOf<String?>(null) }
    var negativeWarning by remember { mutableStateOf<Triple<String, Long, Boolean>?>(null) }
    var confirmDiscard by remember { mutableStateOf(false) }
    var cameraFile by rememberSaveable { mutableStateOf<String?>(null) }

    val msgTooLarge = stringResource(R.string.attachment_too_large)
    val msgUnsupported = stringResource(R.string.attachment_unsupported)
    val msgFailed = stringResource(R.string.attachment_failed)
    val msgSaved = stringResource(R.string.saved)
    val msgNoViewer = stringResource(R.string.no_viewer)
    fun attachError(e: Throwable) {
        val m = when (e) { is AttachmentStore.ImportError.TooLarge -> msgTooLarge; is AttachmentStore.ImportError.Unsupported -> msgUnsupported; else -> msgFailed }
        scope.launch { snackbar.showSnackbar(m) }
    }
    fun onPicked(uri: Uri?) { if (uri != null) form.addAttachment(uri, replacing, ::attachError); replacing = null }

    val camera = rememberLauncherForActivityResult(ActivityResultContracts.TakePicture()) { ok ->
        val path = cameraFile
        if (ok && path != null) form.addAttachment(Uri.fromFile(File(path)), replacing, ::attachError)
        replacing = null
    }
    val gallery = rememberLauncherForActivityResult(ActivityResultContracts.PickVisualMedia()) { onPicked(it) }
    val files = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { onPicked(it) }
    fun launchCamera() {
        val dir = File(ctx.cacheDir, "camera").apply { mkdirs() }
        val file = File(dir, "photo_${System.currentTimeMillis()}.jpg")
        cameraFile = file.path
        vm.allowExternalActivity()
        camera.launch(FileProvider.getUriForFile(ctx, Exporter.authority(ctx), file))
    }

    val errors = form.errors(snap)
    val shown = if (form.showErrors) errors else emptyMap()
    val isEdit = editId > 0
    val title = stringResource(when {
        isEdit -> R.string.edit_entry
        form.type == TxnType.INCOME -> R.string.add_income
        form.type == TxnType.EXPENSE -> R.string.add_expense
        else -> R.string.add_transfer
    })

    fun close() { form.discard(); nav.popBackStack() }
    fun hasInput() = form.amount.isNotBlank() || form.description.isNotBlank() || form.pending.isNotEmpty()
    BackHandler { if (hasInput() && !isEdit) confirmDiscard = true else close() }

    val budgetNear = stringResource(R.string.budget_toast_near)
    val budgetOver = stringResource(R.string.budget_toast_over)
    val belowPaid = stringResource(R.string.inv_err_entry_below_applied)
    fun doSave(addAnother: Boolean) {
        // Warn straight away if this entry pushes a budget to ≥ 80 % or over.
        val candidate = form.buildTxn()
        val before = snap.txns.filter { it.id != candidate.id || candidate.id == 0L }
        val worse = com.cashbook.core.Budgets.worsened(snap.budgets.filter { it.cashbookId == candidate.cashbookId }, before, before + candidate,
            snap.categoryById, java.time.YearMonth.from(candidate.date))
        form.save(onDone = {
            worse.firstOrNull()?.let { p ->
                vm.toast(if (p.status == com.cashbook.core.BudgetStatus.OVER) budgetOver.format(snap.categoryName(p.budget.categoryId), f.amount(-p.remaining))
                else budgetNear.format(snap.categoryName(p.budget.categoryId), p.percent))
            }
            if (addAnother) { form.resetForNext(); scope.launch { snackbar.showSnackbar(msgSaved) } }
            else { vm.toast(msgSaved); nav.popBackStack() }
        }, onError = { e ->
            val m = if (e is com.cashbook.app.data.LedgerRepository.InvoiceException) belowPaid else e.localizedMessage ?: msgFailed
            scope.launch { snackbar.showSnackbar(m) }
        })
    }

    fun attemptSave(addAnother: Boolean) {
        form.showErrors = true
        if (form.errors(snap).isNotEmpty()) {
            scope.launch { scroll.animateScrollTo(0) }  // bring the highlighted fields into view
            scope.launch { snackbar.showSnackbar(ctx.getString(R.string.fix_errors)) }; return
        }
        val neg = form.negativeCheck(snap)
        if (neg != null) {
            negativeWarning = Triple(neg.first.name, neg.second, addAnother)
            return
        }
        doSave(addAnother)
    }

    AppScaffold(title = title, onBack = { if (hasInput() && !isEdit) confirmDiscard = true else close() }, snackbar = snackbar) { pad ->
        Column(Modifier.fillMaxSize().padding(pad).imePadding().verticalScroll(scroll).padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp)) {
            if (form.busy) LinearProgressIndicator(Modifier.fillMaxWidth())
            if (!isEdit || form.isInitialized) {
                SingleChoiceSegmentedButtonRow(Modifier.fillMaxWidth()) {
                    TxnType.entries.forEachIndexed { i, t ->
                        SegmentedButton(selected = form.type == t, enabled = !isEdit,
                            onClick = { if (form.type != t) { form.type = t; form.applyDefaultAccounts(snap, s) } },
                            shape = SegmentedButtonDefaults.itemShape(i, 3),
                            icon = { Icon(typeIcon(t), null) }) { Text(txnTypeLabel(t), maxLines = 1) }
                    }
                }
            }
            val activeCbs = snap.cashbooks.filter { !it.archived || it.id == form.cashbookId }
            if (activeCbs.size > 1) {
                DropdownField(stringResource(R.string.cashbook), activeCbs.map { it.id }, form.cashbookId.takeIf { it != 0L },
                    labelOf = { snap.cashbookById[it]?.name ?: "" }, enabled = !isEdit,
                    onSelect = { form.cashbookId = it; form.applyDefaultAccounts(snap, s) },
                    isError = "cashbook" in shown)
            }
            MoneyField(form.amount, { form.amount = it }, stringResource(R.string.amount_required),
                error = shown["amount"]?.let { amountError(it) })
            DateField(stringResource(R.string.date_required), LocalDate.ofEpochDay(form.date), { form.date = it.toEpochDay() },
                isError = "date" in shown, supporting = if ("date" in shown) stringResource(R.string.err_before_opening) else null)

            val accounts = snap.accounts.filter { it.cashbookId == form.cashbookId && (!it.archived || it.id == form.accountId || it.id == form.toAccountId) }
            if (form.type == TxnType.TRANSFER) {
                PickerField(stringResource(R.string.from_account), snap.accountById[form.accountId]?.name ?: "", { picker = "account" },
                    isError = "account" in shown, supporting = if ("account" in shown) stringResource(R.string.err_account) else null,
                    leading = snap.accountById[form.accountId]?.let { accountIcon(it.type) } ?: Icons.Filled.AccountBalanceWallet)
                PickerField(stringResource(R.string.to_account), snap.accountById[form.toAccountId]?.name ?: "", { picker = "to" },
                    isError = "to" in shown, supporting = shown["to"]?.let { if (it == TxnFormViewModel.Err.SAME_ACCOUNT) stringResource(R.string.err_same_account) else stringResource(R.string.err_account) },
                    leading = Icons.Filled.AccountBalanceWallet)
                val amt = (com.cashbook.core.Money.parse(form.amount) as? com.cashbook.core.Money.ParseResult.Ok)?.paise
                if (amt != null && form.accountId != 0L && form.toAccountId != 0L && form.accountId != form.toAccountId) {
                    InfoBanner(stringResource(R.string.transfer_preview, snap.names.account(form.accountId), f.amount(amt), snap.names.account(form.toAccountId), f.amount(amt)),
                        icon = typeIcon(TxnType.TRANSFER), color = fc.transferBg)
                }
            } else {
                PickerField(stringResource(if (form.type == TxnType.INCOME) R.string.income_category else R.string.expense_category),
                    snap.categoryName(form.categoryId.takeIf { it > 0 }), { picker = "category" }, isError = "category" in shown,
                    supporting = if ("category" in shown) stringResource(R.string.err_category) else null,
                    leading = snap.categoryById[form.categoryId]?.let { categoryIcon(it.icon) } ?: Icons.Filled.Category)
                PickerField(stringResource(if (form.type == TxnType.INCOME) R.string.receiving_account else R.string.paying_account),
                    snap.accountById[form.accountId]?.name ?: "", { picker = "account" }, isError = "account" in shown,
                    supporting = if ("account" in shown) stringResource(R.string.err_account) else stringResource(R.string.account_vs_mode_hint),
                    leading = snap.accountById[form.toAccountId]?.let { accountIcon(it.type) } ?: Icons.Filled.AccountBalanceWallet)
            }
            DropdownField(stringResource(R.string.payment_mode), PaymentMode.entries, form.mode, labelOf = { paymentModeLabel(it) }, onSelect = { form.mode = it })
            if (form.type != TxnType.TRANSFER) {
                PickerField(stringResource(if (form.type == TxnType.INCOME) R.string.received_from else R.string.paid_to),
                    snap.names.party(form.partyId.takeIf { it > 0 }).ifEmpty { stringResource(R.string.optional) }, { picker = "party" }, leading = Icons.Filled.Person)
            }
            OutlinedTextField(form.description, { form.description = it }, label = { Text(stringResource(R.string.description)) },
                modifier = Modifier.fillMaxWidth(), keyboardOptions = KeyboardOptions(capitalization = KeyboardCapitalization.Sentences), maxLines = 3)
            // a learned category for this wording, offered while no category is chosen (never applied silently)
            if (form.type != TxnType.TRANSFER && form.categoryId <= 0) {
                val kind = if (form.type == TxnType.INCOME) CategoryKind.INCOME else CategoryKind.EXPENSE
                com.cashbook.core.CategoryRules.find(snap.categoryRules, form.description)
                    ?.let { r -> snap.categoryById[r.categoryId] }?.takeIf { it.kind == kind && !it.archived }?.let { c ->
                        androidx.compose.material3.AssistChip(onClick = { form.categoryId = c.id },
                            label = { Text(stringResource(R.string.use_category_x, snap.categoryName(c.id))) },
                            leadingIcon = { androidx.compose.material3.Icon(categoryIcon(c.icon), null) })
                    }
            }
            OutlinedTextField(form.reference, { form.reference = it }, singleLine = true, modifier = Modifier.fillMaxWidth(),
                label = { Text(stringResource(when (form.type) { TxnType.EXPENSE -> R.string.bill_number; TxnType.INCOME -> R.string.reference_number; else -> R.string.reference_number })) })
            OutlinedTextField(form.tags, { form.tags = it }, singleLine = true, modifier = Modifier.fillMaxWidth(),
                label = { Text(stringResource(R.string.tags)) }, supportingText = { Text(stringResource(R.string.tags_hint)) })
            OutlinedTextField(form.notes, { form.notes = it }, label = { Text(stringResource(R.string.notes)) }, modifier = Modifier.fillMaxWidth(), minLines = 2, maxLines = 5)

            SectionCard(stringResource(R.string.attachments)) {
                Text(stringResource(R.string.attachment_limits), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                val removed = form.removed
                form.existing.filter { it.id !in removed }.forEach { a ->
                    AttachmentItem(AttachmentUi("e:${a.id}", deps.attachments.file(a.storedName), a.fileName, a.mimeType, a.sizeBytes),
                        onRemove = { form.removeAttachment("e:${a.id}") }, onReplace = { replacing = "e:${a.id}"; vm.allowExternalActivity(); files.launch(MIME_TYPES) },
                        onOpenFailed = { scope.launch { snackbar.showSnackbar(msgNoViewer) } }, beforeExternal = vm::allowExternalActivity)
                }
                form.pending.forEach { a ->
                    AttachmentItem(AttachmentUi("p:${a.storedName}", deps.attachments.file(a.storedName), a.fileName, a.mimeType, a.sizeBytes),
                        onRemove = { form.removeAttachment("p:${a.storedName}") }, onReplace = { replacing = "p:${a.storedName}"; vm.allowExternalActivity(); files.launch(MIME_TYPES) },
                        onOpenFailed = { scope.launch { snackbar.showSnackbar(msgNoViewer) } }, beforeExternal = vm::allowExternalActivity)
                }
                Row(Modifier.fillMaxWidth().padding(top = 8.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    OutlinedButton(onClick = { launchCamera() }, Modifier.weight(1f)) { Icon(Icons.Filled.PhotoCamera, null); Text(" " + stringResource(R.string.camera), maxLines = 1) }
                    OutlinedButton(onClick = { vm.allowExternalActivity(); gallery.launch(PickVisualMediaRequest(ActivityResultContracts.PickVisualMedia.ImageOnly)) }, Modifier.weight(1f)) {
                        Icon(Icons.Filled.PhotoLibrary, null); Text(" " + stringResource(R.string.gallery), maxLines = 1) }
                    OutlinedButton(onClick = { vm.allowExternalActivity(); files.launch(MIME_TYPES) }, Modifier.weight(1f)) {
                        Icon(Icons.Filled.Description, null); Text(" " + stringResource(R.string.file), maxLines = 1) }
                }
            }
            HorizontalDivider()
            Button(onClick = { attemptSave(false) }, enabled = !form.busy, modifier = Modifier.fillMaxWidth().height(52.dp)) { Text(stringResource(R.string.save)) }
            if (!isEdit) OutlinedButton(onClick = { attemptSave(true) }, enabled = !form.busy, modifier = Modifier.fillMaxWidth().height(48.dp)) { Text(stringResource(R.string.save_and_add_another)) }
            TextButton(onClick = { if (hasInput() && !isEdit) confirmDiscard = true else close() }, modifier = Modifier.fillMaxWidth()) { Text(stringResource(R.string.cancel)) }
            Spacer(Modifier.height(24.dp))
        }
    }

    // ----- pickers -----
    when (picker) {
        "category" -> {
            val kind = if (form.type == TxnType.INCOME) CategoryKind.INCOME else CategoryKind.EXPENSE
            val cats = snap.categoriesOf(kind).filter { !it.archived || it.id == form.categoryId }
            val ordered = cats.filter { it.parentId == null }.flatMap { p -> listOf(p) + cats.filter { it.parentId == p.id } } +
                cats.filter { c -> c.parentId != null && cats.none { it.id == c.parentId } }
            SearchPickerSheet(stringResource(R.string.select_category),
                ordered.map { PickItem(it.id, snap.categoryName(it.id), icon = categoryIcon(it.icon), indent = it.parentId != null) },
                onPick = { form.categoryId = it?.id ?: 0; picker = null }, onDismiss = { picker = null },
                createLabel = stringResource(R.string.new_category), onCreate = { q -> newCategory = q; picker = null })
        }
        "account", "to" -> {
            val accounts = snap.accounts.filter { it.cashbookId == form.cashbookId && !it.archived }
            SearchPickerSheet(stringResource(R.string.select_account),
                accounts.map { a -> PickItem(a.id, a.name, accountTypeLabel(a.type) + if (a.last4.isNotBlank()) " ••${a.last4}" else "", accountIcon(a.type)) },
                onPick = { p ->
                    if (picker == "to") form.toAccountId = p?.id ?: 0 else {
                        form.accountId = p?.id ?: 0
                        if (form.type != TxnType.TRANSFER) snap.accountById[form.accountId]?.let { a ->
                            if (a.type == com.cashbook.core.AccountType.CASH) form.mode = PaymentMode.CASH
                            else if (form.mode == PaymentMode.CASH) form.mode = PaymentMode.UPI
                        }
                    }
                    picker = null
                }, onDismiss = { picker = null })
        }
        "party" -> {
            SearchPickerSheet(stringResource(R.string.select_party),
                snap.parties.filter { !it.archived || it.id == form.partyId }.map { PickItem(it.id, it.name, it.mobile) },
                onPick = { form.partyId = it?.id ?: 0; picker = null }, onDismiss = { picker = null },
                createLabel = stringResource(R.string.new_party), onCreate = { q -> newParty = q; picker = null },
                allowNone = stringResource(R.string.no_party))
        }
    }

    newCategory?.let { initial ->
        var name by remember { mutableStateOf(initial) }
        val kind = if (form.type == TxnType.INCOME) CategoryKind.INCOME else CategoryKind.EXPENSE
        var parent by remember { mutableStateOf(0L) }
        AlertDialog(
            onDismissRequest = { newCategory = null },
            title = { Text(stringResource(R.string.new_category)) },
            text = {
                Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    OutlinedTextField(name, { name = it }, label = { Text(stringResource(R.string.name)) }, singleLine = true)
                    val parents = listOf(0L) + snap.categoriesOf(kind).filter { it.parentId == null && !it.archived }.map { it.id }
                    InlineChoice(stringResource(R.string.parent_category), parents, parent, labelOf = { if (it == 0L) stringResource(R.string.none_top_level) else snap.categoryName(it) },
                        onSelect = { parent = it })
                }
            },
            confirmButton = {
                TextButton(enabled = name.isNotBlank(), onClick = {
                    vm.run { val id = ledger.saveCategory(0, kind, name, parent.takeIf { it > 0 }, "category"); form.categoryId = id }
                    newCategory = null
                }) { Text(stringResource(R.string.create)) }
            },
            dismissButton = { TextButton(onClick = { newCategory = null }) { Text(stringResource(R.string.cancel)) } },
        )
    }

    newParty?.let { initial ->
        var name by remember { mutableStateOf(initial) }
        var mobile by remember { mutableStateOf("") }
        var ptype by remember { mutableStateOf(if (form.type == TxnType.INCOME) PartyType.CUSTOMER else PartyType.SUPPLIER) }
        AlertDialog(
            onDismissRequest = { newParty = null },
            title = { Text(stringResource(R.string.new_party)) },
            text = {
                Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    OutlinedTextField(name, { name = it }, label = { Text(stringResource(R.string.name)) }, singleLine = true)
                    InlineChoice(stringResource(R.string.party_type), PartyType.entries, ptype, labelOf = { partyTypeLabel(it) }, onSelect = { ptype = it })
                    OutlinedTextField(mobile, { mobile = it.filter { c -> c.isDigit() || c == '+' || c == ' ' }.take(16) }, label = { Text(stringResource(R.string.mobile)) },
                        singleLine = true, keyboardOptions = KeyboardOptions(keyboardType = androidx.compose.ui.text.input.KeyboardType.Phone))
                }
            },
            confirmButton = {
                TextButton(enabled = name.isNotBlank(), onClick = {
                    vm.run { val id = ledger.saveParty(PartyEntity(name = name, type = ptype.name, mobile = mobile.trim(), createdAt = 0, updatedAt = 0)); form.partyId = id }
                    newParty = null
                }) { Text(stringResource(R.string.create)) }
            },
            dismissButton = { TextButton(onClick = { newParty = null }) { Text(stringResource(R.string.cancel)) } },
        )
    }

    negativeWarning?.let { (acc, bal, addAnother) ->
        AlertDialog(
            onDismissRequest = { negativeWarning = null },
            icon = { Icon(Icons.Filled.Warning, null, tint = fc.warning) },
            title = { Text(stringResource(R.string.negative_title)) },
            text = { Text(stringResource(if (s.allowNegative) R.string.negative_warn else R.string.negative_blocked, acc, f.amount(bal))) },
            confirmButton = {
                if (s.allowNegative) TextButton(onClick = { negativeWarning = null; doSave(addAnother) }) { Text(stringResource(R.string.save_anyway)) }
                else TextButton(onClick = { negativeWarning = null }) { Text(stringResource(R.string.ok)) }
            },
            dismissButton = { if (s.allowNegative) TextButton(onClick = { negativeWarning = null }) { Text(stringResource(R.string.cancel)) } },
        )
    }

    if (confirmDiscard) {
        AlertDialog(
            onDismissRequest = { confirmDiscard = false },
            title = { Text(stringResource(R.string.discard_title)) },
            text = { Text(stringResource(R.string.discard_text)) },
            confirmButton = { TextButton(onClick = { confirmDiscard = false; close() }) { Text(stringResource(R.string.discard), color = MaterialTheme.colorScheme.error) } },
            dismissButton = { TextButton(onClick = { confirmDiscard = false }) { Text(stringResource(R.string.keep_editing)) } },
        )
    }
}

private val MIME_TYPES = arrayOf("application/pdf", "image/jpeg", "image/png")

@Composable
fun amountError(e: TxnFormViewModel.Err): String = stringResource(when (e) {
    TxnFormViewModel.Err.AMOUNT_EMPTY -> R.string.err_amount_required
    TxnFormViewModel.Err.AMOUNT_ZERO -> R.string.err_amount_positive
    TxnFormViewModel.Err.AMOUNT_DECIMALS -> R.string.err_amount_decimals
    TxnFormViewModel.Err.AMOUNT_LARGE -> R.string.err_amount_large
    else -> R.string.err_amount_invalid
})
