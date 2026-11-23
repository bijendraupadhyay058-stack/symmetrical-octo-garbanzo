package com.cashbook.app.ui.settings

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Info
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.size
import androidx.compose.ui.graphics.asImageBitmap
import kotlinx.coroutines.launch
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.input.KeyboardCapitalization
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.navigation.NavHostController
import com.cashbook.app.R
import com.cashbook.app.ui.AppViewModel
import com.cashbook.app.ui.components.AppScaffold
import com.cashbook.app.ui.components.DropdownField
import com.cashbook.app.ui.components.InfoBanner
import com.cashbook.core.Gst
import com.cashbook.core.backup.BusinessProfileDto

/** Seller details printed on tax invoices. */
@Composable
fun BusinessProfileScreen(vm: AppViewModel, nav: NavHostController) {
    val profile by vm.businessProfile.collectAsStateWithLifecycle()
    val ctx = LocalContext.current
    var loaded by rememberSaveable { mutableStateOf(false) }
    var name by rememberSaveable { mutableStateOf("") }
    var address by rememberSaveable { mutableStateOf("") }
    var gstin by rememberSaveable { mutableStateOf("") }
    var state by rememberSaveable { mutableStateOf("") }
    var phone by rememberSaveable { mutableStateOf("") }
    var email by rememberSaveable { mutableStateOf("") }
    var bank by rememberSaveable { mutableStateOf("") }
    var accName by rememberSaveable { mutableStateOf("") }
    var accNo by rememberSaveable { mutableStateOf("") }
    var ifsc by rememberSaveable { mutableStateOf("") }
    var upi by rememberSaveable { mutableStateOf("") }
    var terms by rememberSaveable { mutableStateOf("") }
    var signatory by rememberSaveable { mutableStateOf("") }
    LaunchedEffect(profile) {
        if (loaded) return@LaunchedEffect
        profile.let { p -> name = p.name; address = p.address; gstin = p.gstin; state = p.stateCode; phone = p.phone; email = p.email
            bank = p.bankName; accName = p.accountName; accNo = p.accountNumber; ifsc = p.ifsc; upi = p.upiId; terms = p.terms; signatory = p.signatory }
        loaded = true
    }
    val gstinOk = gstin.isBlank() || Gst.isValidGstin(gstin)
    val upiOk = upi.isBlank() || com.cashbook.core.Upi.isValidVpa(upi)
    val ifscOk = ifsc.isBlank() || ifsc.uppercase().matches(Regex("^[A-Z]{4}0[A-Z0-9]{6}$"))
    AppScaffold(title = stringResource(R.string.business_profile), onBack = { nav.popBackStack() }) { pad ->
        Column(Modifier.fillMaxSize().padding(pad).imePadding().verticalScroll(rememberScrollState()).padding(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            InfoBanner(stringResource(R.string.business_profile_intro), icon = Icons.Filled.Info)
            OutlinedTextField(name, { name = it }, label = { Text(stringResource(R.string.bp_name)) }, singleLine = true, modifier = Modifier.fillMaxWidth(),
                keyboardOptions = KeyboardOptions(capitalization = KeyboardCapitalization.Words))
            OutlinedTextField(address, { address = it }, label = { Text(stringResource(R.string.address)) }, minLines = 2, maxLines = 4, modifier = Modifier.fillMaxWidth())
            OutlinedTextField(gstin, { v -> gstin = v.uppercase().filter { it.isLetterOrDigit() }.take(15); Gst.stateFromGstin(gstin)?.let { if (gstin.length == 15) state = it } },
                label = { Text(stringResource(R.string.gstin_optional)) }, singleLine = true, isError = !gstinOk,
                supportingText = if (!gstinOk) ({ Text(stringResource(R.string.gstin_invalid_check)) }) else null, modifier = Modifier.fillMaxWidth())
            DropdownField(stringResource(R.string.state_ut), listOf("") + Gst.STATES.keys, state, labelOf = { if (it.isEmpty()) stringResource(R.string.not_set) else Gst.stateLabel(it) },
                onSelect = { state = it }, supporting = stringResource(R.string.state_hint), modifier = Modifier.fillMaxWidth())
            OutlinedTextField(phone, { phone = it.filter { c -> c.isDigit() || c in "+ -" }.take(20) }, label = { Text(stringResource(R.string.mobile)) }, singleLine = true,
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Phone), modifier = Modifier.fillMaxWidth())
            OutlinedTextField(email, { email = it }, label = { Text(stringResource(R.string.email)) }, singleLine = true,
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Email), modifier = Modifier.fillMaxWidth())
            BrandingSection(vm)
            Text(stringResource(R.string.bp_payment_details), style = MaterialTheme.typography.titleMedium)
            Text(stringResource(R.string.bp_payment_hint), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            OutlinedTextField(bank, { bank = it }, label = { Text(stringResource(R.string.bank_name_optional)) }, singleLine = true, modifier = Modifier.fillMaxWidth())
            OutlinedTextField(accName, { accName = it }, label = { Text(stringResource(R.string.bp_account_name)) }, singleLine = true, modifier = Modifier.fillMaxWidth())
            OutlinedTextField(accNo, { accNo = it.filter(Char::isDigit).take(18) }, label = { Text(stringResource(R.string.bp_account_number)) }, singleLine = true,
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number), modifier = Modifier.fillMaxWidth())
            OutlinedTextField(ifsc, { ifsc = it.uppercase().filter(Char::isLetterOrDigit).take(11) }, label = { Text(stringResource(R.string.bp_ifsc)) }, singleLine = true,
                isError = !ifscOk, modifier = Modifier.fillMaxWidth())
            OutlinedTextField(upi, { upi = it.trim() }, label = { Text(stringResource(R.string.bp_upi)) }, singleLine = true, isError = !upiOk,
                supportingText = { Text(stringResource(if (upiOk) R.string.upi_qr_hint else R.string.upi_invalid)) }, modifier = Modifier.fillMaxWidth())
            OutlinedTextField(terms, { terms = it }, label = { Text(stringResource(R.string.bp_terms)) }, minLines = 2, maxLines = 5, modifier = Modifier.fillMaxWidth())
            OutlinedTextField(signatory, { signatory = it }, label = { Text(stringResource(R.string.bp_signatory)) }, singleLine = true, modifier = Modifier.fillMaxWidth())
            InfoBanner(stringResource(R.string.no_credentials_note), icon = Icons.Filled.Info)
            Button(enabled = gstinOk && ifscOk && upiOk, onClick = {
                vm.run { settings.updateBusinessProfile(BusinessProfileDto(name, address, gstin, state, phone, email, bank, accName, accNo, ifsc.uppercase(), upi, terms, signatory)) }
                vm.toast(ctx.getString(R.string.saved)); nav.popBackStack()
            }, modifier = Modifier.fillMaxWidth()) { Text(stringResource(R.string.save)) }
        }
    }
}


/** Logo and signature images printed on invoices and notes (picked from the gallery, no permission needed). */
@Composable
private fun BrandingSection(vm: AppViewModel) {
    val store = vm.deps?.attachments ?: return
    val scope = androidx.compose.runtime.rememberCoroutineScope()
    var version by androidx.compose.runtime.remember { androidx.compose.runtime.mutableIntStateOf(0) }
    val failed = stringResource(R.string.attachment_failed)
    var target by androidx.compose.runtime.remember { mutableStateOf(com.cashbook.app.data.AttachmentStore.Brand.LOGO) }
    val picker = androidx.activity.compose.rememberLauncherForActivityResult(androidx.activity.result.contract.ActivityResultContracts.PickVisualMedia()) { uri ->
        if (uri != null) scope.launch {
            val ok = runCatching { kotlinx.coroutines.withContext(kotlinx.coroutines.Dispatchers.IO) { store.importBrand(target, uri) } }.isSuccess
            if (!ok) vm.toast(failed)
            version++
        }
    }
    Text(stringResource(R.string.bp_branding), style = MaterialTheme.typography.titleMedium)
    Text(stringResource(R.string.bp_branding_hint), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
    com.cashbook.app.data.AttachmentStore.Brand.entries.forEach { brand ->
        val bmp = androidx.compose.runtime.remember(version) { store.brandBitmap(brand) }
        androidx.compose.foundation.layout.Row(Modifier.fillMaxWidth(), verticalAlignment = androidx.compose.ui.Alignment.CenterVertically) {
            androidx.compose.foundation.layout.Box(Modifier.size(width = 120.dp, height = 56.dp)
                .background(androidx.compose.ui.graphics.Color.White, MaterialTheme.shapes.small)
                .border(1.dp, MaterialTheme.colorScheme.outlineVariant, MaterialTheme.shapes.small), contentAlignment = androidx.compose.ui.Alignment.Center) {
                if (bmp != null) androidx.compose.foundation.Image(bmp.asImageBitmap(), stringResource(if (brand == com.cashbook.app.data.AttachmentStore.Brand.LOGO) R.string.bp_logo else R.string.bp_signature_image),
                    Modifier.padding(4.dp).fillMaxSize(), contentScale = androidx.compose.ui.layout.ContentScale.Fit)
                else Text(stringResource(R.string.none), style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.outline)
            }
            Column(Modifier.weight(1f).padding(start = 12.dp)) {
                Text(stringResource(if (brand == com.cashbook.app.data.AttachmentStore.Brand.LOGO) R.string.bp_logo else R.string.bp_signature_image), style = MaterialTheme.typography.bodyLarge)
                androidx.compose.foundation.layout.Row {
                    TextButton(onClick = { target = brand; vm.allowExternalActivity()
                        picker.launch(androidx.activity.result.PickVisualMediaRequest(androidx.activity.result.contract.ActivityResultContracts.PickVisualMedia.ImageOnly)) }) {
                        Text(stringResource(if (bmp == null) R.string.choose_image else R.string.replace)) }
                    if (bmp != null) TextButton(onClick = { store.removeBrand(brand); version++ }) { Text(stringResource(R.string.remove)) }
                }
            }
        }
    }
}
