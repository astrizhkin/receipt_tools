package com.biarum.receipt_tools

import android.content.Intent
import android.provider.Settings
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel
import androidx.core.content.FileProvider
import java.io.File

class MainActivity : FlutterActivity() {
    // Installs an APK the Dart side already downloaded + sha256-verified.
    // Downloading in Dart (not a plugin's OkHttp) keeps the self-signed-cert
    // bypass working; the file is staged in the cache dir, which
    // res/xml/filepaths.xml covers via cache-path.
    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        // device_info_plus cannot expose ANDROID_ID (removed in 4.0.0), so
        // the app asks for it here; it needs no permission and is stable per
        // device + signing key across reinstalls.
        MethodChannel(
            flutterEngine.dartExecutor.binaryMessenger,
            "receipt_tools/device",
        ).setMethodCallHandler { call, result ->
            if (call.method == "androidId") {
                result.success(
                    Settings.Secure.getString(
                        contentResolver, Settings.Secure.ANDROID_ID,
                    ),
                )
            } else {
                result.notImplemented()
            }
        }
        MethodChannel(
            flutterEngine.dartExecutor.binaryMessenger,
            "receipt_tools/install",
        ).setMethodCallHandler { call, result ->
            if (call.method == "install") {
                val path = call.argument<String>("path")
                if (path == null) {
                    result.error("bad_args", "path required", null)
                    return@setMethodCallHandler
                }
                try {
                    val uri = FileProvider.getUriForFile(
                        this, "$packageName.ota_update_provider", File(path),
                    )
                    val intent = Intent(Intent.ACTION_VIEW).apply {
                        setDataAndType(uri, "application/vnd.android.package-archive")
                        addFlags(
                            Intent.FLAG_ACTIVITY_NEW_TASK or
                                Intent.FLAG_GRANT_READ_URI_PERMISSION,
                        )
                    }
                    startActivity(intent)
                    result.success(true)
                } catch (e: Exception) {
                    result.error("install_failed", e.message, null)
                }
            } else {
                result.notImplemented()
            }
        }
    }
}
