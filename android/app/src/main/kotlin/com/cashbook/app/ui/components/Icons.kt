package com.cashbook.app.ui.components

import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.Undo
import androidx.compose.material.icons.filled.AccountBalance
import androidx.compose.material.icons.filled.AccountBalanceWallet
import androidx.compose.material.icons.filled.AddCircle
import androidx.compose.material.icons.filled.Bolt
import androidx.compose.material.icons.filled.Build
import androidx.compose.material.icons.filled.CardGiftcard
import androidx.compose.material.icons.filled.Category
import androidx.compose.material.icons.filled.DirectionsCar
import androidx.compose.material.icons.filled.Flight
import androidx.compose.material.icons.filled.Gavel
import androidx.compose.material.icons.filled.Handshake
import androidx.compose.material.icons.filled.Home
import androidx.compose.material.icons.filled.Inventory2
import androidx.compose.material.icons.filled.LocalGasStation
import androidx.compose.material.icons.filled.LocalHospital
import androidx.compose.material.icons.filled.Payments
import androidx.compose.material.icons.filled.People
import androidx.compose.material.icons.filled.Percent
import androidx.compose.material.icons.filled.Pets
import androidx.compose.material.icons.filled.PhoneAndroid
import androidx.compose.material.icons.filled.Print
import androidx.compose.material.icons.filled.Receipt
import androidx.compose.material.icons.filled.RemoveCircle
import androidx.compose.material.icons.filled.Restaurant
import androidx.compose.material.icons.filled.Savings
import androidx.compose.material.icons.filled.School
import androidx.compose.material.icons.filled.ShoppingBag
import androidx.compose.material.icons.filled.ShoppingCart
import androidx.compose.material.icons.filled.Store
import androidx.compose.material.icons.filled.Wifi
import androidx.compose.material.icons.filled.Work
import androidx.compose.ui.graphics.vector.ImageVector
import com.cashbook.core.AccountType

fun categoryIcon(key: String): ImageVector = when (key) {
    "store" -> Icons.Filled.Store; "work" -> Icons.Filled.Work; "build" -> Icons.Filled.Build
    "handshake" -> Icons.Filled.Handshake; "percent" -> Icons.Filled.Percent; "home" -> Icons.Filled.Home
    "undo" -> Icons.AutoMirrored.Filled.Undo; "add_circle" -> Icons.Filled.AddCircle; "cart" -> Icons.Filled.ShoppingCart
    "people" -> Icons.Filled.People; "bolt" -> Icons.Filled.Bolt; "wifi" -> Icons.Filled.Wifi
    "car" -> Icons.Filled.DirectionsCar; "inventory" -> Icons.Filled.Inventory2; "print" -> Icons.Filled.Print
    "bank" -> Icons.Filled.AccountBalance; "gavel" -> Icons.Filled.Gavel; "food" -> Icons.Filled.Restaurant
    "remove_circle" -> Icons.Filled.RemoveCircle; "medical" -> Icons.Filled.LocalHospital; "school" -> Icons.Filled.School
    "fuel" -> Icons.Filled.LocalGasStation; "phone" -> Icons.Filled.PhoneAndroid; "gift" -> Icons.Filled.CardGiftcard
    "savings" -> Icons.Filled.Savings; "receipt" -> Icons.Filled.Receipt; "shopping" -> Icons.Filled.ShoppingBag
    "flight" -> Icons.Filled.Flight; "pets" -> Icons.Filled.Pets
    else -> Icons.Filled.Category
}

fun accountIcon(t: AccountType): ImageVector = when (t) {
    AccountType.CASH -> Icons.Filled.Payments
    AccountType.BANK -> Icons.Filled.AccountBalance
    AccountType.WALLET -> Icons.Filled.AccountBalanceWallet
    AccountType.OTHER -> Icons.Filled.Savings
}
