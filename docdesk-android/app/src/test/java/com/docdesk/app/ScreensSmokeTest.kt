package com.docdesk.app

import androidx.compose.runtime.Composable
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onAllNodesWithText
import androidx.navigation.compose.rememberNavController
import com.docdesk.app.data.ThemeMode
import com.docdesk.app.ui.Nav
import com.docdesk.app.ui.theme.DocDeskTheme
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

/** Opens every screen in its initial state and checks it renders its title without crashing. */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35])
class ScreensSmokeTest {

    @get:Rule val rule = createComposeRule()

    private fun check(expected: String, dark: Boolean = false, content: @Composable (Nav) -> Unit) {
        rule.setContent { DocDeskTheme(if (dark) ThemeMode.DARK else ThemeMode.LIGHT) { content(Nav(rememberNavController())) } }
        rule.waitForIdle()
        assertTrue("'$expected' not shown", rule.onAllNodesWithText(expected, substring = true).fetchSemanticsNodes().isNotEmpty())
    }

    @Test fun home() = check("Select a file") { com.docdesk.app.ui.home.HomeScreen(it) }
    @Test fun homeDark() = check("Search tools and files", dark = true) { com.docdesk.app.ui.home.HomeScreen(it) }
    @Test fun files() = check("My Files") { com.docdesk.app.ui.files.FilesScreen(it) }
    @Test fun history() = check("History") { com.docdesk.app.ui.history.HistoryScreen(it) }
    @Test fun settings() = check("Lock DocDesk") { com.docdesk.app.ui.settings.SettingsScreen() }
    @Test fun viewer() = check("Choose a PDF to view") { com.docdesk.app.ui.viewer.ViewerScreen(it, null) }
    @Test fun merge() = check("Add PDF files") { com.docdesk.app.ui.merge.MergeScreen(it, null) }
    @Test fun split() = check("Choose a PDF to split") { com.docdesk.app.ui.split.SplitScreen(it, null) }
    @Test fun organize() = check("Choose a PDF to organise") { com.docdesk.app.ui.organize.OrganizeScreen(it, null) }
    @Test fun pdfToExcel() = check("Choose a PDF with tables") { com.docdesk.app.ui.convert.PdfToExcelScreen(it, null) }
    @Test fun pdfToWord() = check("Creates an editable Word") { com.docdesk.app.ui.convert.PdfToWordScreen(it, null) }
    @Test fun excelToPdf() = check("Choose an Excel file") { com.docdesk.app.ui.convert.OfficeToPdfScreen(it, null, excel = true) }
    @Test fun wordToPdf() = check("Choose a Word file") { com.docdesk.app.ui.convert.OfficeToPdfScreen(it, null, excel = false) }
    @Test fun edit() = check("Choose a PDF to annotate") { com.docdesk.app.ui.edit.EditPdfScreen(it, null) }
    @Test fun scan() = check("Scan with camera") { com.docdesk.app.ui.scan.ScanScreen(it) }
    @Test fun ocr() = check("Choose a scanned PDF") { com.docdesk.app.ui.scan.OcrScreen(it, null) }
    @Test fun create() = check("Choose Word, Excel or photo files") { com.docdesk.app.ui.create.CreatePdfScreen(it, null) }
    @Test fun form() = check("Choose a PDF form") { com.docdesk.app.ui.tools.FillFormScreen(it, null) }
    @Test fun watermark() = check("Add watermark") { com.docdesk.app.ui.tools.MoreToolsScreen(it, null, com.docdesk.app.ui.tools.MoreTool.WATERMARK) }
    @Test fun numbers() = check("Page numbers") { com.docdesk.app.ui.tools.MoreToolsScreen(it, null, com.docdesk.app.ui.tools.MoreTool.NUMBERS) }
    @Test fun compress() = check("Compress PDF") { com.docdesk.app.ui.tools.MoreToolsScreen(it, null, com.docdesk.app.ui.tools.MoreTool.COMPRESS) }
    @Test fun sign() = check("Choose a PDF to sign or check") { com.docdesk.app.ui.sign.SignScreen(it, null) }
    @Test fun compare() = check("Choose the ORIGINAL") { com.docdesk.app.ui.tools.CompareScreen(it, null) }
    @Test fun images() = check("PDF to JPG / PNG") { com.docdesk.app.ui.tools.ExportImagesScreen(it, null) }
    @Test fun statements() = check("Choose one or more bank statements") { com.docdesk.app.ui.tools.StatementsScreen(it, null) }
    @Test fun redact() = check("Choose a PDF to clean") { com.docdesk.app.ui.tools.FindRedactScreen(it, null) }
    @Test fun batch() = check("Choose several PDFs") { com.docdesk.app.ui.tools.BatchScreen(it, null) }
    @Test fun invoices() = check("Choose GST invoices") { com.docdesk.app.ui.tools.InvoicesScreen(it, null) }
    @Test fun search() = check("Search inside files") { com.docdesk.app.ui.tools.SearchFilesScreen(it) }
    @Test fun protect() = check("Choose a PDF to protect") { com.docdesk.app.ui.tools.SecurityScreen(it, null, unlock = false) }
    @Test fun unlock() = check("Choose a protected PDF") { com.docdesk.app.ui.tools.SecurityScreen(it, null, unlock = true) }
    @Test fun toSize() = check("Make it small enough") { com.docdesk.app.ui.tools.PortalScreen(it, null, com.docdesk.app.ui.tools.PortalTool.TARGET_SIZE) }
    @Test fun splitSize() = check("Split into parts under") { com.docdesk.app.ui.tools.PortalScreen(it, null, com.docdesk.app.ui.tools.PortalTool.SPLIT_SIZE) }
    @Test fun fitPages() = check("Put every page on A4") { com.docdesk.app.ui.tools.PortalScreen(it, null, com.docdesk.app.ui.tools.PortalTool.FIT_PAGES) }
    @Test fun crop() = check("Choose a PDF to crop") { com.docdesk.app.ui.tools.CropScreen(it, null) }
    @Test fun flatten() = check("Choose a PDF to flatten") { com.docdesk.app.ui.tools.FlattenScreen(it, null) }
    @Test fun repair() = check("Choose a damaged PDF") { com.docdesk.app.ui.tools.RepairScreen(it, null) }
    @Test fun missingResult() = check("no longer available") { com.docdesk.app.ui.result.ResultScreen(it, 99999) }
}
