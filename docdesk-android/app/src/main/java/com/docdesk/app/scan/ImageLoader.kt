package com.docdesk.app.scan

import android.content.Context
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Matrix
import android.media.ExifInterface
import android.net.Uri

/** Decodes images at a bounded size and applies EXIF orientation. */
object ImageLoader {
    fun load(context: Context, uri: Uri, maxSide: Int): Bitmap? {
        val cr = context.contentResolver
        val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
        cr.openInputStream(uri)?.use { BitmapFactory.decodeStream(it, null, bounds) } ?: return null
        var sample = 1
        while (maxOf(bounds.outWidth, bounds.outHeight) / (sample * 2) >= maxSide) sample *= 2
        val bmp = cr.openInputStream(uri)?.use { BitmapFactory.decodeStream(it, null, BitmapFactory.Options().apply { inSampleSize = sample }) } ?: return null
        val rotation = runCatching {
            cr.openInputStream(uri)?.use { ExifInterface(it).getAttributeInt(ExifInterface.TAG_ORIENTATION, ExifInterface.ORIENTATION_NORMAL) }
        }.getOrNull()?.let { when (it) { ExifInterface.ORIENTATION_ROTATE_90 -> 90; ExifInterface.ORIENTATION_ROTATE_180 -> 180; ExifInterface.ORIENTATION_ROTATE_270 -> 270; else -> 0 } } ?: 0
        val scaled = maxOf(bmp.width, bmp.height).let { m ->
            if (m > maxSide) Bitmap.createScaledBitmap(bmp, bmp.width * maxSide / m, bmp.height * maxSide / m, true).also { if (it !== bmp) bmp.recycle() } else bmp
        }
        if (rotation == 0) return scaled
        val r = Bitmap.createBitmap(scaled, 0, 0, scaled.width, scaled.height, Matrix().apply { postRotate(rotation.toFloat()) }, true)
        if (r !== scaled) scaled.recycle()
        return r
    }
}
