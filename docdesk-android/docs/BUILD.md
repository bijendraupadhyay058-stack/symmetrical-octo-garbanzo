# Setup, build and release

## Requirements

| Tool | Version |
|---|---|
| JDK | 17 or newer (tested with 21) |
| Android Studio | Narwhal (2025.1) or newer, or command-line tools only |
| Android SDK | Platform 36, Build-Tools 36 (Gradle downloads missing parts automatically when licences are accepted) |
| Gradle | Wrapper included (8.14.3) – use `./gradlew` |
| Android Gradle Plugin / Kotlin | 8.13.2 / 2.2.21 (see `gradle/libs.versions.toml`) |

## Open and run in Android Studio

1. *File › Open…* and choose the `docdesk-android` folder (not the repository root).
2. Let Gradle sync. If prompted, install SDK Platform 36.
3. Pick a device (phone with USB debugging, or an emulator image with Google Play for the camera scanner) and press **Run**.

## Command line

```bash
cd docdesk-android
echo "sdk.dir=$HOME/Android/Sdk" > local.properties     # path to your Android SDK
./gradlew :core:test                 # engine tests (29 tests incl. real sample documents)
./gradlew :app:assembleDebug         # debug APK
./gradlew :app:lintDebug             # Android Lint
adb install -r app/build/outputs/apk/debug/app-debug.apk
```

The debug build installs as `com.docdesk.app.debug`, so it can sit next to a release build.

Regenerate sample documents (optional): `pip install reportlab pypdf pillow openpyxl python-docx && python3 samples/make_samples.py`.

## Signed release build

1. Create a keystore once (keep it safe and backed up – you cannot update a Play app without it):
   ```bash
   keytool -genkeypair -v -keystore docdesk-release.jks -alias docdesk -keyalg RSA -keysize 4096 -validity 10000
   ```
2. Create `docdesk-android/keystore.properties` (ignored by git – never commit it):
   ```properties
   storeFile=docdesk-release.jks
   storePassword=********
   keyAlias=docdesk
   keyPassword=********
   ```
3. Build:
   ```bash
   ./gradlew :app:bundleRelease     # Android App Bundle for Google Play → app/build/outputs/bundle/release/
   ./gradlew :app:assembleRelease   # signed APK for direct distribution → app/build/outputs/apk/release/
   ```
   Without `keystore.properties` the release build is produced **unsigned** (`app-release-unsigned.apk`); sign it with `apksigner` if needed.

Release builds use R8 (code shrinking + resource shrinking). Rules for PdfBox-Android are in `app/proguard-rules.pro`.

### Size

| Build | Size |
|---|---|
| Debug APK (unminified, all ABIs) | ~75 MB |
| Release APK, universal (all ABIs) | ~52 MB |
| Release via App Bundle, per device (arm64) | ~22 MB (≈11 MB is the on-device OCR native library) |

Prefer the App Bundle for Play. For direct APK distribution consider ABI splits (`splits { abi { … } }`).

### Before publishing

- Review the merged manifest (*Android Studio › AndroidManifest.xml › Merged Manifest*) for permissions added by libraries.
- Fill in the Play Console **Data safety** form: DocDesk collects no data and makes no network requests itself; the document scanner runs in Google Play services.
- Test the release build on real devices (R8 can remove reflective code): open/merge/split a PDF, run PDF→Excel and PDF→Word, OCR, Word/Excel→PDF and save an annotated PDF.
- Bump `versionCode`/`versionName` in `app/build.gradle.kts`.

## Continuous integration

`.github/workflows/android.yml` runs the core tests, lint and a debug build on every push/PR that touches `docdesk-android/`, and uploads the debug APK as an artifact.

## Troubleshooting

| Problem | Fix |
|---|---|
| `SDK location not found` | Create `local.properties` with `sdk.dir=…` or set `ANDROID_HOME` |
| Gradle "429 Too Many Requests" from Maven Central | Re-run; or use a mirror such as `https://repo1.maven.org/maven2/` via an init script |
| Camera scanner says unavailable | Device/emulator needs Google Play services and internet on first use; *Import images* works without it |
| OutOfMemory on very large files | Process fewer pages at a time (page ranges); close other apps |
