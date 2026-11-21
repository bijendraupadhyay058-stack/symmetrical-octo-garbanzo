package com.docdesk.app.ui.statements

import android.net.Uri
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.setValue
import com.docdesk.core.DateOrder
import com.docdesk.core.LedgerRule
import com.docdesk.core.NumberStyle
import com.docdesk.core.PageStatus
import com.docdesk.core.ReviewSession

/** Tally export settings chosen before extraction. */
data class TallyChoice(val bankLedger: String, val defaultLedger: String)

/**
 * A bank-statement review in progress. Held in memory only (statements are confidential and
 * passwords must never be written to disk); if Android ends the app, the review starts again.
 */
class StatementReview(
    val session: ReviewSession,
    /** Source name → file and password (in memory only) for showing the source page. */
    val sources: Map<String, Pair<Uri, String?>>,
    val pages: List<PageStatus>,
    val settingsNotes: List<String>,
    val outputName: String,
    val style: NumberStyle,
    val dateOrder: DateOrder,
    val csv: Boolean,
    val tally: TallyChoice?,
    val rules: List<LedgerRule>,
    val partySummaries: Boolean,
    val inputNames: List<String>,
    val warnings: List<String>,
) {
    /** Bumped after every change so Compose re-reads the session. */
    var version by mutableIntStateOf(0)
    fun changed() { version++ }
}

object StatementReviewStore {
    var current: StatementReview? = null
}
