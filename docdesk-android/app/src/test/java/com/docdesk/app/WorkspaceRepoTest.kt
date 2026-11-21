package com.docdesk.app

import android.net.Uri
import com.docdesk.core.DocStatus
import com.docdesk.core.FolderKind
import com.docdesk.core.Workspace
import java.io.File
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35])
class WorkspaceRepoTest {
    private val app get() = androidx.test.core.app.ApplicationProvider.getApplicationContext<DocDeskApp>()

    @Test fun clientFoldersDocsChecklistsAndBackup() = runBlocking {
        val ws = app.workspace
        val id = ws.createClient("Sharma Traders", "F-102")
        val fy = ws.createFolder(id, null, "FY 2024-25", FolderKind.FINANCIAL_YEAR)
        val gst = ws.createFolder(id, fy, "GST", FolderKind.CATEGORY)
        val f = File(app.filesDir, "GSTR-3B March.pdf").apply { writeText("%PDF-1.4 test") }
        assertEquals(1, ws.addDocuments(id, gst, listOf(Uri.fromFile(f)), app.files))
        var doc = ws.dao.observeDocs(id).first().single()
        assertEquals("GSTR-3B March.pdf", doc.name); assertEquals(DocStatus.PENDING_REVIEW.name, doc.status)
        assertTrue(ws.isAvailable(doc))
        ws.setStatus(doc, DocStatus.REVIEWED)
        ws.updateDoc(ws.dao.observeDocs(id).first().single().copy(tags = "gst, march"), "tags updated")
        doc = ws.dao.observeDocs(id).first().single()
        assertEquals("REVIEWED", doc.status)
        assertTrue(Workspace.matches("march gst", doc.name, doc.tags))
        // Removing the GST folder moves the file up to the FY folder.
        ws.deleteFolder(ws.dao.observeFolders(id).first().first { it.id == gst })
        assertEquals(fy, ws.dao.observeDocs(id).first().single().folderId)
        // Checklist from a template.
        val cl = ws.createChecklist(id, "ITR filing", Workspace.checklistTemplates["ITR filing"]!!)
        val items = ws.dao.observeItems(id).first()
        assertEquals(Workspace.checklistTemplates["ITR filing"]!!.size, items.size)
        ws.toggleItem(id, items[0])
        assertTrue(ws.dao.observeItems(id).first().first { it.id == items[0].id }.done)
        // Backup and restore round trip.
        val json = com.docdesk.app.data.Backup.export(app)
        assertFalse(json.contains("test")) // document contents are never included
        ws.dao.replaceAll(emptyList(), emptyList(), emptyList(), emptyList(), emptyList(), emptyList())
        assertEquals(0, ws.dao.allClients().size)
        val r = com.docdesk.app.data.Backup.restore(app, json)
        assertEquals(1, r.clients); assertEquals(1, r.documents)
        assertEquals("Sharma Traders", ws.dao.allClients().single().name)
        assertEquals(1, ws.dao.observeChecklists(id).first().size); assertTrue(cl > 0)
        // A moved/deleted file shows as unavailable.
        f.delete()
        assertFalse(ws.isAvailable(ws.dao.allDocs().single()))
        assertTrue(ws.dao.observeActivity(id).first().any { it.text.contains("Checklist") })
    }

    @Test fun recycleBin() {
        val files = app.files
        val f = File(files.myFilesDir, "Report.pdf").apply { writeText("x") }
        assertTrue(files.moveToTrash(f))
        assertFalse(f.exists())
        assertEquals(listOf("Report.pdf"), files.listTrash().map { it.name })
        File(files.myFilesDir, "Report.pdf").writeText("new") // name taken meanwhile
        val back = files.restoreFromTrash(files.listTrash().single().file)
        assertEquals("Report (2).pdf", back.name); assertEquals("x", back.readText())
        assertTrue(files.moveToTrash(back))
        files.emptyTrash(olderThanMillis = 60_000) // too recent to purge
        assertEquals(1, files.listTrash().size)
        files.emptyTrash()
        assertTrue(files.listTrash().isEmpty())
    }

    @Test fun encryptedBackupRoundTrip() = runBlocking {
        val ws = app.workspace
        ws.createClient("Verma & Co", "")
        File(app.files.myFilesDir, "Balance sheet.pdf").writeText("%PDF secret numbers")
        val target = File(app.cacheDir, "backup.ddbk")
        val o = com.docdesk.app.data.CloudBackup.backupNow(app, Uri.fromFile(target), "backup pass 1".toCharArray(), includeFiles = true, frequency = com.docdesk.app.data.BackupFrequency.OFF)
        assertEquals(1, o.documents)
        val bytes = target.readBytes()
        assertTrue(com.docdesk.core.BackupCrypto.isBackup(bytes))
        assertFalse(String(bytes, Charsets.ISO_8859_1).contains("Verma") || String(bytes, Charsets.ISO_8859_1).contains("secret numbers"))
        // Lose everything, then restore.
        ws.dao.replaceAll(emptyList(), emptyList(), emptyList(), emptyList(), emptyList(), emptyList())
        app.files.myFilesDir.listFiles()!!.forEach { it.delete() }
        try { com.docdesk.app.data.CloudBackup.restore(app, bytes, "wrong".toCharArray()); org.junit.Assert.fail() } catch (e: com.docdesk.core.WrongBackupPasswordException) { }
        val r = com.docdesk.app.data.CloudBackup.restore(app, bytes, "backup pass 1".toCharArray())
        assertEquals(1, r.documentsRestored)
        assertTrue(ws.dao.allClients().any { it.name == "Verma & Co" })
        assertEquals("%PDF secret numbers", File(app.files.myFilesDir, "Balance sheet.pdf").readText())
        // A second restore doesn't overwrite: the document is added under a new name.
        assertEquals(1, com.docdesk.app.data.CloudBackup.restore(app, bytes, "backup pass 1".toCharArray()).documentsRestored)
        assertTrue(File(app.files.myFilesDir, "Balance sheet (2).pdf").exists())
    }
}
