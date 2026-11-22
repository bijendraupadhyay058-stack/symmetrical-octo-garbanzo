package com.cashbook.app.ui.manage

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Close
import androidx.compose.material3.Checkbox
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.saveable.Saver
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import com.cashbook.app.R
import com.cashbook.app.data.LedgerRepository
import com.cashbook.app.ui.components.DropdownField
import com.cashbook.app.ui.components.MoneyField
import com.cashbook.app.ui.components.SectionCard
import com.cashbook.app.ui.components.accountIcon
import com.cashbook.app.ui.components.accountTypeLabel
import com.cashbook.core.AccountType
import com.cashbook.core.Money
import java.time.LocalDate

/** Editable account row used when creating a cashbook (onboarding and "new cashbook"). */
data class AccountDraft(val enabled: Boolean, val type: AccountType, val name: String, val opening: String = "", val bankName: String = "", val last4: String = "") {
    val openingError: Boolean get() = enabled && Money.parseOpening(opening) is Money.ParseResult.Error
    fun toNew(date: LocalDate) = LedgerRepository.NewAccount(name.trim(), type,
        (Money.parseOpening(opening) as? Money.ParseResult.Ok)?.paise ?: 0, date, bankName, last4)

    companion object {
        val ListSaver: Saver<List<AccountDraft>, Any> = Saver(
            save = { list -> list.map { arrayListOf(it.enabled.toString(), it.type.name, it.name, it.opening, it.bankName, it.last4) } },
            restore = { raw -> (raw as List<*>).map { r -> val a = r as List<*>
                AccountDraft(a[0] == "true", AccountType.valueOf(a[1] as String), a[2] as String, a[3] as String, a[4] as String, a[5] as String) } },
        )
    }
}

fun validDrafts(list: List<AccountDraft>) = list.any { it.enabled } && list.none { it.enabled && (it.name.isBlank() || it.openingError) }

@Composable
fun AccountDraftEditor(drafts: List<AccountDraft>, onChange: (List<AccountDraft>) -> Unit, showErrors: Boolean) {
    Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
        drafts.forEachIndexed { i, d ->
            fun upd(n: AccountDraft) = onChange(drafts.toMutableList().also { it[i] = n })
            SectionCard {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Checkbox(d.enabled, { upd(d.copy(enabled = it)) })
                    Icon(accountIcon(d.type), null, tint = MaterialTheme.colorScheme.primary)
                    Spacer(Modifier.width(8.dp))
                    Text(accountTypeLabel(d.type), style = MaterialTheme.typography.titleSmall, modifier = Modifier.weight(1f))
                    if (i >= 3) IconButton(onClick = { onChange(drafts.toMutableList().also { it.removeAt(i) }) }) { Icon(Icons.Filled.Close, stringResource(R.string.remove)) }
                }
                if (d.enabled) Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                    if (i >= 3) DropdownField(stringResource(R.string.account_type), AccountType.entries, d.type, labelOf = { accountTypeLabel(it) }, onSelect = { upd(d.copy(type = it)) })
                    OutlinedTextField(d.name, { upd(d.copy(name = it)) }, label = { Text(stringResource(R.string.account_name)) }, singleLine = true,
                        isError = showErrors && d.name.isBlank(), modifier = Modifier.fillMaxWidth())
                    MoneyField(d.opening, { upd(d.copy(opening = it)) }, stringResource(R.string.opening_balance),
                        error = if (showErrors && d.openingError) stringResource(R.string.err_amount_invalid) else null)
                    if (d.type == AccountType.BANK) Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        OutlinedTextField(d.bankName, { upd(d.copy(bankName = it)) }, label = { Text(stringResource(R.string.bank_name_optional)) }, singleLine = true, modifier = Modifier.weight(1.4f))
                        OutlinedTextField(d.last4, { v -> upd(d.copy(last4 = v.filter { it.isDigit() }.take(4))) }, label = { Text(stringResource(R.string.last4_optional)) },
                            singleLine = true, keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.NumberPassword), modifier = Modifier.weight(1f))
                    }
                }
            }
        }
        TextButton(onClick = { onChange(drafts + AccountDraft(true, AccountType.OTHER, "")) }) {
            Icon(Icons.Filled.Add, null); Text(" " + stringResource(R.string.add_another_account))
        }
        Text(stringResource(R.string.no_credentials_note), style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.padding(horizontal = 4.dp))
    }
}

@Composable
fun defaultDrafts(): List<AccountDraft> = listOf(
    AccountDraft(true, AccountType.CASH, stringResource(R.string.default_cash_name)),
    AccountDraft(true, AccountType.BANK, stringResource(R.string.default_bank_name)),
    AccountDraft(false, AccountType.WALLET, stringResource(R.string.default_wallet_name)),
)
