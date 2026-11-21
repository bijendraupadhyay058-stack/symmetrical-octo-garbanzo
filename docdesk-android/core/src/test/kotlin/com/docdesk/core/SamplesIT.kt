package com.docdesk.core

import java.io.File
import org.apache.pdfbox.pdmodel.PDDocument
import org.apache.pdfbox.text.PDFTextStripper
import org.apache.pdfbox.text.TextPosition
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Assume.assumeTrue
import org.junit.Before
import org.junit.Test

/**
 * Runs the core engine on the real sample documents in samples/out (create them with
 * samples/make_samples.py). Text positions come from desktop Apache PDFBox, whose API matches
 * PdfBox-Android; [words] mirrors app/pdf/PdfTextExtractor.kt – keep the two in sync.
 * Skipped automatically when the sample files are missing.
 */
class SamplesIT {
    private val dir = File("../samples/out")

    @Before fun samplesPresent() = assumeTrue("sample files not generated", File(dir, "bank_statement_text.pdf").exists())

    private fun words(doc: PDDocument, i: Int): PageText {
        val out = mutableListOf<TextWord>()
        val s = object : PDFTextStripper() {
            override fun writeString(text: String, tps: MutableList<TextPosition>) {
                var cur = mutableListOf<TextPosition>()
                fun flush() {
                    if (cur.isEmpty()) return
                    val t = cur.joinToString("") { it.unicode ?: "" }.trim()
                    if (t.isNotEmpty()) {
                        val x = cur.minOf { it.xDirAdj }; val right = cur.maxOf { it.xDirAdj + it.widthDirAdj }
                        val h = cur.maxOf { it.heightDir }.coerceAtLeast(1f); val size = cur.maxOf { it.fontSizeInPt }
                        val fn = cur.first().font?.name?.lowercase() ?: ""
                        out.add(TextWord(t, x, cur.minOf { it.yDirAdj } - h, right - x, h * 1.2f, size, fn.contains("bold"), fn.contains("oblique") || fn.contains("italic")))
                    }
                    cur = mutableListOf()
                }
                for (tp in tps) {
                    val u = tp.unicode ?: continue
                    if (u.isBlank()) { flush(); continue }
                    val prev = cur.lastOrNull()
                    if (prev != null) {
                        val gap = tp.xDirAdj - (prev.xDirAdj + prev.widthDirAdj)
                        val space = (prev.widthOfSpace.takeIf { it > 0 } ?: prev.widthDirAdj).coerceAtLeast(0.5f)
                        if (gap > space * 0.6f || kotlin.math.abs(tp.yDirAdj - prev.yDirAdj) > prev.heightDir * 0.5f) flush()
                    }
                    cur.add(tp)
                }
                flush()
            }
        }
        s.sortByPosition = true; s.startPage = i + 1; s.endPage = i + 1; s.getText(doc)
        val b = doc.getPage(i).cropBox
        return PageText(i, b.width, b.height, out, TextSource.PDF_TEXT)
    }

    @Test fun bankStatement() {
        PDDocument.load(File(dir, "bank_statement_text.pdf")).use { doc ->
            val pages = (0 until doc.numberOfPages).map { words(doc, it) }
            val tables = pages.flatMap { TableExtractor.extract(it) }
            println("BANK: pages=${pages.size} tables=${tables.size} perTable=${tables.map { "${it.columnCount}c/${it.bodyRows.size}r hdr=${it.header?.cells?.map { c -> c.raw }}" }}")
            val combined = TableExtractor.combine(tables)
            println("BANK combined: ${combined.map { "${it.columnCount} cols, ${it.bodyRows.size} rows, types=${it.columnTypes}" }}")
            combined.first().bodyRows.take(3).forEach { println("  ROW " + it.cells.map { c -> c.raw }) }
            val lines = pages.flatMap { p -> LineGrouper.group(p.words).map { it.text } }.filter { it.contains("balance", true) || it.contains("total", true) }
            val r = FinancialChecks.run(combined.first(), NumberStyle.INDIAN, lines)
            println("BANK checks: rows=${r.transactionRows} dr=${r.totalDebit} cr=${r.totalCredit} checked=${r.balanceRowsChecked} mismatches=${r.balanceMismatches} notes=${r.notes} found=${r.statementTotalsFound}")
            val built = ExcelExport.build(tables, ExcelExportOptions())
            println("BANK export: sheets=${built.sheets.map { it.name }} converted=${built.convertedCells} text=${built.textCells} flagged=${built.flaggedCells}")
            assertEquals(1, combined.size)
            assertEquals(55, combined[0].bodyRows.size) // every transaction, wrapped narrations joined
            assertEquals(listOf(ColumnType.DATE, ColumnType.TEXT, ColumnType.TEXT, ColumnType.AMOUNT, ColumnType.AMOUNT, ColumnType.AMOUNT), combined[0].columnTypes)
            assertTrue(combined[0].bodyRows.any { row -> row.cells[1].raw.endsWith("freight charges") })
            assertEquals(emptyList<Int>(), r.balanceMismatches)
            assertEquals(java.math.BigDecimal("513405.27"), r.totalDebit)
            assertTrue(r.notes.any { it.contains("matches the closing balance") })
        }
    }

    @Test fun statementNormalized() {
        PDDocument.load(File(dir, "bank_statement_text.pdf")).use { doc ->
            val tables = (0 until doc.numberOfPages).flatMap { TableExtractor.extract(words(doc, it)) }
            val n = StatementNormalizer.normalize(tables, NumberStyle.INDIAN, DateOrder.DMY, "statement.pdf")!!
            assertEquals(55, n.rows.size)
            assertTrue(n.rows.all { it.date != null && it.flags.isEmpty() })
            assertEquals(emptyList<Int>(), StatementNormalizer.balanceMismatches(n.rows))
            // Review session over a real multi-page statement: rows know their position, order is detected, balances chain.
            assertTrue(n.rows.all { it.top != null && it.bottom != null && it.top!! < it.bottom!! && it.original.isNotEmpty() })
            val session = ReviewSession(n.rows)
            assertTrue(session.orderConfirmed)
            val rec = Reconciler.reconcile(session).single()
            assertEquals(emptyList<Int>(), rec.runningBreaks)
            session.confirmOpening("statement.pdf", session.opening("statement.pdf").value); session.confirmClosing("statement.pdf", session.closing("statement.pdf").value)
            assertEquals(CheckStatus.OK, Reconciler.reconcile(session).single().lines.first { it.label == "Difference" }.status)
            assertEquals(6, BankWorkbook.build(session, emptyList(), emptyList()).size)
            assertEquals(java.math.BigDecimal("513405.27"), n.rows.mapNotNull { it.debit }.fold(java.math.BigDecimal.ZERO, java.math.BigDecimal::add))
            val text = (0 until doc.numberOfPages).map { words(doc, it) }
            assertTrue(text.flatMap { SensitiveFinder.find(it, setOf(SensitiveKind.ACCOUNT)) }.any { it.text == "001234567890" })
        }
    }

    @Test fun invoice() {
        PDDocument.load(File(dir, "invoice.pdf")).use { doc ->
            val t = TableExtractor.extract(words(doc, 0))
            assertEquals(1, t.size)
            assertEquals(listOf("S.No", "Description", "HSN", "Qty", "Rate", "Amount"), t[0].header!!.cells.map { it.raw })
            assertEquals("Toner cartridge 88A", t[0].bodyRows[1].cells[1].raw)
            assertEquals("31,249.35", t[0].bodyRows.last().cells[5].raw)
            val inv = InvoiceExtractor.extract(listOf(words(doc, 0)), "invoice.pdf")
            assertEquals("INV/2024-25/0042", inv.invoiceNo)
            assertEquals(java.time.LocalDate.of(2024, 4, 15), inv.date)
            assertEquals(java.math.BigDecimal("26482.50"), inv.taxable)
            assertEquals(java.math.BigDecimal("31249.35"), inv.total)
            assertEquals(inv.cgst, inv.sgst)
            assertEquals("Tax Invoice", inv.invoiceType)
            assertEquals("Sample Supplies Pvt Ltd", inv.supplierName)
            assertEquals("Example Traders", inv.buyerName)
            assertEquals(listOf("4802", "8443", "4820", "9987"), inv.items.map { it.hsnSac })
            assertEquals("Toner cartridge 88A", inv.items[1].description)
            assertEquals(java.math.BigDecimal("7350.00"), inv.items[1].amount)
            assertEquals(1, inv.page)
        }
    }

    @Test fun mixedToWord() {
        PDDocument.load(File(dir, "report_mixed_text_and_scan.pdf")).use { doc ->
            val d = PdfToDocBuilder.build(listOf(PageContent(words(doc, 0))), WordMode.EDITABLE)
            val paras = d.blocks.filterIsInstance<DocBlock.Paragraph>()
            assertEquals(1, paras[0].headingLevel)
            assertEquals("1. Summary", paras[1].text); assertTrue(paras[1].headingLevel in 1..3)
            assertTrue(paras[2].text.endsWith("for the next year."))
            assertEquals(3, paras.count { it.listLabel == "•" })
        }
    }

    @Test fun workbook() {
        val wb = XlsxReader.read(File(dir, "workbook_multi_sheet.xlsx").inputStream())
        println("XLSX sheets=${wb.sheets.map { "${it.name}(${it.maxRow + 1}x${it.maxCol + 1}, hidden=${it.hidden}, printArea=${it.printArea})" }}")
        println("XLSX warnings=${wb.warnings}")
        val l = wb.sheets[0]
        println("XLSX ledger row4: ${(0..5).map { l.cells[3]?.get(it)?.display }} merges=${l.merges}")
        println("XLSX summary: ${(1..7).map { r -> (0..1).map { wb.sheets[1].cells[r]?.get(it)?.display } }}")
        assertEquals("4,32,438.24", l.cells[3]!![4]!!.display)
        assertEquals("(1,830,000.00)", wb.sheets[1].cells[2]!![1]!!.display)
        assertEquals("23.5%", wb.sheets[1].cells[7]!![1]!!.display)
        assertTrue(wb.warnings.any { it.contains("formula") })
        assertTrue(wb.sheets[3].hidden)
        assertEquals(40, SheetPaginator.paginate(l, SheetPrintOptions()).sumOf { it.rows.size }) // print area A1:F40
    }

    @Test fun word() {
        val d = DocxReader.read(File(dir, "word_tables_images.docx").inputStream())
        d.blocks.forEach { b -> when (b) {
            is DocBlock.Paragraph -> println("DOCX h=${b.headingLevel} list=${b.listLabel} '${b.text.take(70)}' bold=${b.runs.map { it.bold }}")
            is DocBlock.Table -> println("DOCX table ${b.rows.size}x${b.rows[0].size} bordered=${b.bordered} r1=${b.rows[1].map { c -> (c.blocks.firstOrNull() as? DocBlock.Paragraph)?.text }}")
            is DocBlock.Image -> println("DOCX image ${b.format} ${b.widthPt}x${b.heightPt}")
            DocBlock.PageBreak -> println("DOCX pagebreak")
        } }
        val paras = d.blocks.filterIsInstance<DocBlock.Paragraph>()
        assertEquals(3, paras.count { it.listLabel == "•" })
        assertEquals(listOf("1.", "2.", "3."), paras.mapNotNull { it.listLabel?.takeIf { l -> l != "•" } })
        assertTrue(paras.any { it.text.startsWith("यह एक नमूना") })
        assertEquals(1, d.blocks.count { it is DocBlock.Table }); assertEquals(1, d.blocks.count { it is DocBlock.Image })
        assertEquals("Confidential", (d.footer.single() as DocBlock.Paragraph).text)
        assertTrue(d.unsupported.isEmpty())
    }
}
