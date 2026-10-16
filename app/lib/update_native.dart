import 'dart:io';

import 'package:crypto/crypto.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:http/http.dart' as http;
import 'package:path_provider/path_provider.dart';

import 'api.dart';

const _installChannel = MethodChannel('receipt_tools/install');

/// Native (Android) update: download the APK through the app's own HTTP
/// client — so the self-signed-cert bypass applies, unlike a plugin's OkHttp
/// downloader — verify sha256, then hand the file to the system installer via
/// the install channel (FileProvider serves files/ota_update/).
Future<void> performUpdate(
    BuildContext context, ApiClient api, Map<String, dynamic> info) async {
  // cache dir == context.getCacheDir(), covered by <cache-path> in
  // filepaths.xml; app_flutter (getApplicationDocumentsDirectory) is NOT
  // under filesDir and broke the FileProvider lookup
  final docs = await getApplicationCacheDirectory();
  final dir = Directory('${docs.path}/ota_update')..createSync(recursive: true);
  final dest = File('${dir.path}/receipt_tools-update.apk');

  final frac = ValueNotifier<double>(0);
  final nav = Navigator.of(context);
  var dialogOpen = true;
  showDialog<void>(
    context: context,
    barrierDismissible: false,
    builder: (_) => AlertDialog(
      title: const Text('Downloading update'),
      content: ValueListenableBuilder<double>(
        valueListenable: frac,
        builder: (_, f, __) => Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            LinearProgressIndicator(value: f),
            const SizedBox(height: 8),
            Text('${(f * 100).toStringAsFixed(0)}%'),
          ],
        ),
      ),
    ),
  ).then((_) => dialogOpen = false);

  void closeDialog() {
    if (dialogOpen) nav.pop();
  }

  void fail(String msg) {
    debugPrint('update failed: $msg');
    closeDialog();
    if (context.mounted) {
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text('Update failed: $msg')));
    }
  }

  try {
    final streamed = await api.client
        .send(http.Request('GET', api.absoluteUri(info['url'] as String)))
        .timeout(const Duration(seconds: 60));
    if (streamed.statusCode != 200) {
      throw 'HTTP ${streamed.statusCode} on download';
    }
    final total = int.tryParse(streamed.headers['content-length'] ?? '');
    final sink = dest.openWrite();
    var got = 0;
    try {
      await for (final chunk in streamed.stream) {
        sink.add(chunk);
        got += chunk.length;
        if (total != null && total > 0) frac.value = got / total;
      }
    } finally {
      await sink.close();
    }

    final digest = await sha256.bind(dest.openRead()).first;
    final want = (info['sha256'] ?? '').toString();
    if (want.isNotEmpty && digest.toString() != want) {
      await dest.delete();
      throw 'downloaded APK failed checksum verification';
    }

    closeDialog();
    await _installChannel.invokeMethod('install', {'path': dest.path});
    if (context.mounted) {
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
          content: Text('Installer opened — confirm the update there.')));
    }
  } on PlatformException catch (e) {
    fail(e.message ?? e.code);
  } catch (e) {
    fail('$e');
  }
}
