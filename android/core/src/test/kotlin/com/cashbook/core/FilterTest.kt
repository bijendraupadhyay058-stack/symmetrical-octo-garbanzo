package com.cashbook.core

import com.cashbook.core.SampleScenario.d
import com.cashbook.core.SampleScenario.txns
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class FilterTest {
    private val names = object : NameLookup {
        override fun account(id: Long?) = SampleScenario.accounts.firstOrNull { it.id == id }?.name ?: ""
        override fun category(id: Long?) = SampleScenario.categories[id]?.name ?: ""
        override fun party(id: Long?) = ""
    }

    @Test fun searchByTextCategoryAndAmount() {
        assertEquals(listOf(3L), TxnQuery.apply(txns, TxnFilter(query = "internet"), names).map { it.id })
        assertEquals(listOf(2L), TxnQuery.apply(txns, TxnFilter(query = "printing"), names).map { it.id })
        assertEquals(listOf(1L), TxnQuery.apply(txns, TxnFilter(query = "15,000"), names).map { it.id })
    }

    @Test fun filtersCombine() {
        val f = TxnFilter(range = DateRange(d(3), d(5)), accountIds = setOf(SampleScenario.cash.id))
        assertEquals(listOf(2L, 4L), TxnQuery.apply(txns, f, names).map { it.id })
        assertTrue(f.isActive)
        assertFalse(TxnFilter(cashbookIds = setOf(1)).isActive)
        assertEquals(listOf(1L), TxnQuery.apply(txns, TxnFilter(minAmount = 1_000_000), names).map { it.id })
        assertEquals(listOf(4L), TxnQuery.apply(txns, TxnFilter(withAttachmentsOnly = true), names, setOf(4L)).map { it.id })
    }

    @Test fun sorting() {
        assertEquals(listOf(4L, 3L, 2L, 1L), TxnQuery.sort(txns, SortOrder.LATEST).map { it.id })
        assertEquals(listOf(1L, 4L, 2L, 3L), TxnQuery.sort(txns, SortOrder.HIGHEST).map { it.id })
        assertEquals(listOf(3L, 2L, 4L, 1L), TxnQuery.sort(txns, SortOrder.LOWEST).map { it.id })
    }
}
