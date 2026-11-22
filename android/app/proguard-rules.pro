# SQLCipher uses JNI callbacks into these classes.
-keep class net.zetetic.database.** { *; }
-keep class net.zetetic.database.sqlcipher.** { *; }
# kotlinx.serialization (backup format, defined in :core)
-keepattributes *Annotation*, InnerClasses
-keepclassmembers class com.cashbook.core.backup.** {
    *** Companion;
    kotlinx.serialization.KSerializer serializer(...);
}
-keep,includedescriptorclasses class com.cashbook.core.backup.**$$serializer { *; }
