package com.docdesk.app.ui

import android.content.Intent
import android.net.Uri
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Folder
import androidx.compose.material.icons.filled.History
import androidx.compose.material.icons.filled.Home
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material3.Icon
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalContext
import androidx.navigation.NavGraph.Companion.findStartDestination
import androidx.navigation.NavHostController
import androidx.navigation.NavType
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.currentBackStackEntryAsState
import androidx.navigation.compose.rememberNavController
import androidx.navigation.navArgument
import com.docdesk.app.ui.convert.OfficeToPdfScreen
import com.docdesk.app.ui.convert.PdfToExcelScreen
import com.docdesk.app.ui.convert.PdfToWordScreen
import com.docdesk.app.ui.edit.EditPdfScreen
import com.docdesk.app.ui.files.FilesScreen
import com.docdesk.app.ui.history.HistoryScreen
import com.docdesk.app.ui.home.HomeScreen
import com.docdesk.app.ui.merge.MergeScreen
import com.docdesk.app.ui.organize.OrganizeScreen
import com.docdesk.app.ui.result.ResultScreen
import com.docdesk.app.ui.scan.OcrScreen
import com.docdesk.app.ui.scan.ScanScreen
import com.docdesk.app.ui.settings.SettingsScreen
import com.docdesk.app.ui.split.SplitScreen
import com.docdesk.app.ui.viewer.ViewerScreen

object Routes {
    const val HOME = "home"; const val FILES = "files"; const val HISTORY = "history"; const val SETTINGS = "settings"
    const val VIEWER = "viewer"; const val MERGE = "merge"; const val SPLIT = "split"; const val ORGANIZE = "organize"
    const val PDF_EXCEL = "pdf2excel"; const val PDF_WORD = "pdf2word"; const val EXCEL_PDF = "excel2pdf"; const val WORD_PDF = "word2pdf"
    const val EDIT = "edit"; const val SCAN = "scan"; const val OCR = "ocr"; const val RESULT = "result"
    const val CREATE = "create"; const val FORM = "form"; const val WATERMARK = "watermark"; const val NUMBERS = "numbers"; const val COMPRESS = "compress"
    const val SIGN = "sign"; const val COMPARE = "compare"; const val IMAGES = "images"
    const val STATEMENTS = "statements"; const val REDACT = "redact"; const val BATCH = "batch"
    const val INVOICES = "invoices"; const val SEARCH = "searchfiles"
    const val PROTECT = "protect"; const val UNLOCK = "unlock"
    const val TO_SIZE = "tosize"; const val SPLIT_SIZE = "splitsize"; const val FIT = "fitpages"

    fun withInput(route: String, uri: Uri?) = if (uri == null) route else "$route?input=${Uri.encode(uri.toString())}"
}

private data class Tab(val route: String, val label: String, val icon: ImageVector)
private val tabs = listOf(
    Tab(Routes.HOME, "Home", Icons.Default.Home), Tab(Routes.FILES, "Files", Icons.Default.Folder),
    Tab(Routes.HISTORY, "History", Icons.Default.History), Tab(Routes.SETTINGS, "Settings", Icons.Default.Settings),
)

/** Navigation helper passed to screens. */
class Nav(private val c: NavHostController) {
    fun back() { if (!c.popBackStack()) c.navigate(Routes.HOME) }
    fun to(route: String, input: Uri? = null) = c.navigate(Routes.withInput(route, input))
    fun result(id: Long) = c.navigate("${Routes.RESULT}/$id")
    /**
     * Returns a callback that shows a result. If the user is still on the screen that started
     * the operation, that screen is replaced (Back returns to where they came from); if they
     * have moved elsewhere meanwhile, the result is simply opened on top.
     */
    fun resultCallback(): (Long) -> Unit {
        val origin = c.currentBackStackEntry?.id
        return { id ->
            if (origin != null && c.currentBackStackEntry?.id == origin) c.navigate("${Routes.RESULT}/$id") { popUpTo(c.currentDestination!!.id) { inclusive = true } }
            else result(id)
        }
    }
}

@Composable
fun AppNav(incoming: Uri?, onIncomingHandled: () -> Unit, incomingMany: Boolean = false, openRoute: String? = null, onRouteHandled: () -> Unit = {}) {
    val controller = rememberNavController()
    val nav = Nav(controller)
    val entry by controller.currentBackStackEntryAsState()
    val currentRoute = entry?.destination?.route
    val context = LocalContext.current

    LaunchedEffect(incoming) {
        if (incoming != null) {
            runCatching { context.contentResolver.takePersistableUriPermission(incoming, Intent.FLAG_GRANT_READ_URI_PERMISSION) }
            val type = com.docdesk.app.DocDeskApp.instance.files.describe(incoming).type
            // PDFs open in the viewer; Word, Excel and photos go to Create PDF.
            if (type == com.docdesk.app.data.DocType.PDF && !incomingMany) nav.to(Routes.VIEWER, incoming) else nav.to(Routes.CREATE, if (incomingMany) null else incoming)
            onIncomingHandled()
        }
    }

    LaunchedEffect(openRoute) {
        if (openRoute != null) { runCatching { nav.to(openRoute) }; onRouteHandled() }
    }

    val showBar = tabs.any { it.route == currentRoute }
    Scaffold(
        bottomBar = {
            if (showBar) NavigationBar {
                tabs.forEach { t ->
                    NavigationBarItem(
                        selected = currentRoute == t.route,
                        onClick = {
                            controller.navigate(t.route) {
                                popUpTo(controller.graph.findStartDestination().id) { saveState = true }
                                launchSingleTop = true; restoreState = true
                            }
                        },
                        icon = { Icon(t.icon, contentDescription = null) },
                        label = { Text(t.label) },
                    )
                }
            }
        },
    ) { pad ->
        NavHost(controller, startDestination = Routes.HOME, modifier = if (showBar) Modifier.padding(bottom = pad.calculateBottomPadding()) else Modifier) {
            composable(Routes.HOME) { HomeScreen(nav) }
            composable(Routes.FILES) { FilesScreen(nav) }
            composable(Routes.HISTORY) { HistoryScreen(nav) }
            composable(Routes.SETTINGS) { SettingsScreen() }
            fun tool(route: String, content: @Composable (Uri?) -> Unit) = composable(
                "$route?input={input}",
                arguments = listOf(navArgument("input") { type = NavType.StringType; nullable = true; defaultValue = null }),
            ) { e -> content(e.arguments?.getString("input")?.let { Uri.parse(it) }) }
            tool(Routes.VIEWER) { ViewerScreen(nav, it) }
            tool(Routes.MERGE) { MergeScreen(nav, it) }
            tool(Routes.SPLIT) { SplitScreen(nav, it) }
            tool(Routes.ORGANIZE) { OrganizeScreen(nav, it) }
            tool(Routes.PDF_EXCEL) { PdfToExcelScreen(nav, it) }
            tool(Routes.PDF_WORD) { PdfToWordScreen(nav, it) }
            tool(Routes.EXCEL_PDF) { OfficeToPdfScreen(nav, it, excel = true) }
            tool(Routes.WORD_PDF) { OfficeToPdfScreen(nav, it, excel = false) }
            tool(Routes.EDIT) { EditPdfScreen(nav, it) }
            tool(Routes.SCAN) { ScanScreen(nav) }
            tool(Routes.OCR) { OcrScreen(nav, it) }
            tool(Routes.CREATE) { com.docdesk.app.ui.create.CreatePdfScreen(nav, it) }
            tool(Routes.FORM) { com.docdesk.app.ui.tools.FillFormScreen(nav, it) }
            tool(Routes.WATERMARK) { com.docdesk.app.ui.tools.MoreToolsScreen(nav, it, com.docdesk.app.ui.tools.MoreTool.WATERMARK) }
            tool(Routes.NUMBERS) { com.docdesk.app.ui.tools.MoreToolsScreen(nav, it, com.docdesk.app.ui.tools.MoreTool.NUMBERS) }
            tool(Routes.TO_SIZE) { com.docdesk.app.ui.tools.PortalScreen(nav, it, com.docdesk.app.ui.tools.PortalTool.TARGET_SIZE) }
            tool(Routes.SPLIT_SIZE) { com.docdesk.app.ui.tools.PortalScreen(nav, it, com.docdesk.app.ui.tools.PortalTool.SPLIT_SIZE) }
            tool(Routes.FIT) { com.docdesk.app.ui.tools.PortalScreen(nav, it, com.docdesk.app.ui.tools.PortalTool.FIT_PAGES) }
            tool(Routes.PROTECT) { com.docdesk.app.ui.tools.SecurityScreen(nav, it, unlock = false) }
            tool(Routes.UNLOCK) { com.docdesk.app.ui.tools.SecurityScreen(nav, it, unlock = true) }
            tool(Routes.INVOICES) { com.docdesk.app.ui.tools.InvoicesScreen(nav, it) }
            tool(Routes.SEARCH) { com.docdesk.app.ui.tools.SearchFilesScreen(nav) }
            tool(Routes.STATEMENTS) { com.docdesk.app.ui.tools.StatementsScreen(nav, it) }
            tool(Routes.REDACT) { com.docdesk.app.ui.tools.FindRedactScreen(nav, it) }
            tool(Routes.BATCH) { com.docdesk.app.ui.tools.BatchScreen(nav, it) }
            tool(Routes.SIGN) { com.docdesk.app.ui.sign.SignScreen(nav, it) }
            tool(Routes.COMPARE) { com.docdesk.app.ui.tools.CompareScreen(nav, it) }
            tool(Routes.IMAGES) { com.docdesk.app.ui.tools.ExportImagesScreen(nav, it) }
            tool(Routes.COMPRESS) { com.docdesk.app.ui.tools.MoreToolsScreen(nav, it, com.docdesk.app.ui.tools.MoreTool.COMPRESS) }
            composable("${Routes.RESULT}/{id}", arguments = listOf(navArgument("id") { type = NavType.LongType })) { e ->
                ResultScreen(nav, e.arguments?.getLong("id") ?: -1)
            }
        }
    }
}
