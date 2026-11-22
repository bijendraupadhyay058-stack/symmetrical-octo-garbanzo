package com.cashbook.app.ui.manage

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ExtendedFloatingActionButton
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.ListItem
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Tab
import androidx.compose.material3.TabRow
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.navigation.NavHostController
import com.cashbook.app.R
import com.cashbook.app.data.DefaultData
import com.cashbook.app.ui.AppViewModel
import com.cashbook.app.ui.components.AppScaffold
import com.cashbook.app.ui.components.DropdownField
import com.cashbook.app.ui.components.InlineChoice
import com.cashbook.app.ui.components.InfoBanner
import com.cashbook.app.ui.components.SwitchRow
import com.cashbook.app.ui.components.categoryIcon
import com.cashbook.app.ui.nav.Routes
import com.cashbook.core.CategoryKind
import kotlinx.coroutines.launch

@Composable
fun CategoriesScreen(vm: AppViewModel, nav: NavHostController) {
    val snap by vm.snapshot.collectAsStateWithLifecycle()
    var tab by rememberSaveable { mutableIntStateOf(1) }
    val kind = if (tab == 0) CategoryKind.INCOME else CategoryKind.EXPENSE
    val cats = snap.categoriesOf(kind)
    val usage = snap.txns.groupingBy { it.categoryId }.eachCount()
    val ordered = cats.filter { it.parentId == null }.flatMap { p -> listOf(p) + cats.filter { it.parentId == p.id } }
    AppScaffold(title = stringResource(R.string.categories), onBack = { nav.popBackStack() }, floating = {
        ExtendedFloatingActionButton(onClick = { nav.navigate(Routes.category(0, kind.name)) }, icon = { Icon(Icons.Filled.Add, null) }, text = { Text(stringResource(R.string.new_category)) })
    }) { pad ->
        Column(Modifier.fillMaxSize().padding(pad)) {
            TabRow(tab) {
                Tab(tab == 0, { tab = 0 }, text = { Text(stringResource(R.string.income)) })
                Tab(tab == 1, { tab = 1 }, text = { Text(stringResource(R.string.expenses)) })
            }
            LazyColumn {
                items(ordered, key = { it.id }) { c ->
                    ListItem(
                        headlineContent = { Text(c.name) },
                        supportingContent = { Text(stringResource(R.string.used_in_n, usage[c.id] ?: 0) + if (c.archived) " · " + stringResource(R.string.archived) else "") },
                        leadingContent = { Icon(categoryIcon(c.icon), null, tint = MaterialTheme.colorScheme.primary) },
                        modifier = Modifier.clickable { nav.navigate(Routes.category(c.id, kind.name)) }
                            .padding(start = if (c.parentId != null) 24.dp else 0.dp).alpha(if (c.archived) 0.55f else 1f),
                    )
                    HorizontalDivider()
                }
                item { Box(Modifier.padding(40.dp)) }
            }
        }
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
fun CategoryEditScreen(vm: AppViewModel, nav: NavHostController, id: Long, kindName: String) {
    val snap by vm.snapshot.collectAsStateWithLifecycle()
    val existing = snap.categoryById[id]
    val kind = existing?.kind ?: runCatching { CategoryKind.valueOf(kindName) }.getOrDefault(CategoryKind.EXPENSE)
    var name by rememberSaveable { mutableStateOf("") }
    var parent by rememberSaveable { mutableStateOf(0L) }
    var icon by rememberSaveable { mutableStateOf("category") }
    var loaded by rememberSaveable { mutableStateOf(id == 0L) }
    var usage by remember { mutableIntStateOf(0) }
    var deleteDialog by remember { mutableStateOf(false) }
    var reassignTo by remember { mutableStateOf(0L) }
    val scope = rememberCoroutineScope()
    LaunchedEffect(existing) {
        if (!loaded && existing != null) { name = existing.name; parent = existing.parentId ?: 0; icon = existing.icon; loaded = true }
        if (id > 0) usage = vm.deps?.ledger?.categoryUsage(id) ?: 0
    }
    val hasChildren = snap.categories.any { it.parentId == id }
    AppScaffold(title = stringResource(if (id == 0L) R.string.new_category else R.string.edit_category), onBack = { nav.popBackStack() }) { pad ->
        Column(Modifier.fillMaxSize().padding(pad).verticalScroll(rememberScrollState()).padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Text(stringResource(if (kind == CategoryKind.INCOME) R.string.income_category else R.string.expense_category), style = MaterialTheme.typography.labelLarge)
            OutlinedTextField(name, { name = it }, label = { Text(stringResource(R.string.name)) }, singleLine = true, modifier = Modifier.fillMaxWidth())
            if (!hasChildren) {
                val parents = listOf(0L) + snap.categoriesOf(kind).filter { it.parentId == null && it.id != id && !it.archived }.map { it.id }
                DropdownField(stringResource(R.string.parent_category), parents, parent, labelOf = { if (it == 0L) stringResource(R.string.none_top_level) else snap.categoryName(it) },
                    onSelect = { parent = it }, modifier = Modifier.fillMaxWidth())
            }
            Text(stringResource(R.string.icon), style = MaterialTheme.typography.labelLarge)
            FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                DefaultData.iconKeys.forEach { k ->
                    Box(Modifier.size(44.dp).background(if (k == icon) MaterialTheme.colorScheme.primaryContainer else MaterialTheme.colorScheme.surfaceVariant, CircleShape)
                        .clickable { icon = k }.semantics { contentDescription = k }, contentAlignment = Alignment.Center) {
                        Icon(categoryIcon(k), null, tint = if (k == icon) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                }
            }
            if (id > 0) {
                InfoBanner(stringResource(R.string.rename_category_info, usage))
                SwitchRow(stringResource(R.string.archived), existing?.archived == true, { a -> vm.run { ledger.setCategoryArchived(id, a) } }, stringResource(R.string.archive_category_desc))
            }
            Button(onClick = {
                if (name.isBlank()) return@Button
                vm.run { ledger.saveCategory(id, kind, name, parent.takeIf { it > 0 }, icon) }
                nav.popBackStack()
            }, enabled = name.isNotBlank(), modifier = Modifier.fillMaxWidth()) { Text(stringResource(R.string.save)) }
            if (id > 0) OutlinedButton(onClick = { deleteDialog = true }, modifier = Modifier.fillMaxWidth()) { Text(stringResource(R.string.delete), color = MaterialTheme.colorScheme.error) }
        }
    }
    if (deleteDialog) {
        val others = snap.categoriesOf(kind).filter { it.id != id && !it.archived }
        AlertDialog(
            onDismissRequest = { deleteDialog = false },
            title = { Text(stringResource(R.string.delete_category)) },
            text = {
                Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    if (usage > 0) {
                        Text(stringResource(R.string.category_in_use, usage))
                        InlineChoice(stringResource(R.string.move_entries_to), others.map { it.id }, reassignTo.takeIf { it > 0 }, labelOf = { snap.categoryName(it) }, onSelect = { reassignTo = it })
                    } else Text(stringResource(R.string.delete_category_text))
                }
            },
            confirmButton = {
                TextButton(enabled = usage == 0 || reassignTo > 0, onClick = {
                    deleteDialog = false
                    scope.launch {
                        val ok = vm.deps?.ledger?.deleteCategory(id, reassignTo.takeIf { it > 0 }) == true
                        if (ok) nav.popBackStack()
                    }
                }) { Text(stringResource(R.string.delete), color = MaterialTheme.colorScheme.error) }
            },
            dismissButton = { TextButton(onClick = { deleteDialog = false }) { Text(stringResource(R.string.cancel)) } },
        )
    }
}
