package com.cashbook.app.data

import com.cashbook.core.CategoryKind

/** Preloaded, user-editable categories: (name, icon key). Names are stored in the user's language at first launch. */
object DefaultData {
    val incomeEn = listOf(
        "Sales" to "store", "Professional fees" to "work", "Service charges" to "build", "Commission" to "handshake",
        "Interest received" to "percent", "Rent received" to "home", "Refund received" to "undo", "Other income" to "add_circle",
    )
    val expenseEn = listOf(
        "Purchases" to "cart", "Office rent" to "home", "Salary and wages" to "people", "Electricity" to "bolt",
        "Telephone and internet" to "wifi", "Travel and conveyance" to "car", "Office supplies" to "inventory",
        "Repairs and maintenance" to "build", "Printing and stationery" to "print", "Bank charges" to "bank",
        "Professional expenses" to "work", "Taxes and statutory payments" to "gavel", "Food and refreshments" to "food",
        "Other expenses" to "remove_circle",
    )
    val incomeHi = listOf(
        "बिक्री" to "store", "व्यावसायिक शुल्क" to "work", "सेवा शुल्क" to "build", "कमीशन" to "handshake",
        "प्राप्त ब्याज" to "percent", "प्राप्त किराया" to "home", "प्राप्त रिफंड" to "undo", "अन्य आय" to "add_circle",
    )
    val expenseHi = listOf(
        "खरीद" to "cart", "कार्यालय किराया" to "home", "वेतन और मज़दूरी" to "people", "बिजली" to "bolt",
        "टेलीफ़ोन और इंटरनेट" to "wifi", "यात्रा और वाहन" to "car", "कार्यालय सामग्री" to "inventory",
        "मरम्मत और रखरखाव" to "build", "छपाई और स्टेशनरी" to "print", "बैंक शुल्क" to "bank",
        "व्यावसायिक व्यय" to "work", "कर और वैधानिक भुगतान" to "gavel", "भोजन और जलपान" to "food",
        "अन्य व्यय" to "remove_circle",
    )

    fun categories(language: String): List<Triple<CategoryKind, String, String>> {
        val (inc, exp) = if (language == "hi") incomeHi to expenseHi else incomeEn to expenseEn
        return inc.map { Triple(CategoryKind.INCOME, it.first, it.second) } + exp.map { Triple(CategoryKind.EXPENSE, it.first, it.second) }
    }

    /** Icon keys offered in the category editor. */
    val iconKeys = listOf("category", "store", "work", "build", "handshake", "percent", "home", "undo", "add_circle", "cart",
        "people", "bolt", "wifi", "car", "inventory", "print", "bank", "gavel", "food", "remove_circle", "medical", "school",
        "fuel", "phone", "gift", "savings", "receipt", "shopping", "flight", "pets")
}
