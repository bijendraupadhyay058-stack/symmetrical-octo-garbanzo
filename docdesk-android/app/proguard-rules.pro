# PdfBox-Android uses reflection for some font/filter classes.
-keep class com.tom_roush.pdfbox.** { *; }
-keep class com.tom_roush.fontbox.** { *; }
-keep class com.tom_roush.harmony.** { *; }
-dontwarn com.tom_roush.pdfbox.filter.JPXFilter
-dontwarn com.gemalto.jp2.**
-dontwarn org.bouncycastle.**
# Room entities
-keep class com.docdesk.app.data.db.** { *; }
