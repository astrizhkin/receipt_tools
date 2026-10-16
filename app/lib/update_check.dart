import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:package_info_plus/package_info_plus.dart';

import 'api.dart';

// storage + update mechanics are platform-specific
import 'storage_web.dart' if (dart.library.io) 'storage_io.dart';
import 'update_stub.dart' if (dart.library.io) 'update_native.dart';

const _kDismissed = 'update_dismissed_code';
const _kLastCheck = 'update_last_check';

/// Self-distributed APK update: GET /app_update, compare version_code with the
/// installed buildNumber, then download (sha256-verified, through the app's
/// own HTTP client) and open the system installer. Auto-checks are throttled
/// to once/24h and respect a per-version "Later" dismissal.
Future<void> checkForUpdate(BuildContext context, ApiClient api,
    {bool manual = false}) async {
  if (kIsWeb) return;
  final pkg = await PackageInfo.fromPlatform();
  final local = int.tryParse(pkg.buildNumber) ?? 0;

  if (!manual) {
    final last = DateTime.tryParse(await secureRead(_kLastCheck) ?? '');
    if (last != null && DateTime.now().difference(last).inHours < 24) return;
  }
  await secureWrite(_kLastCheck, DateTime.now().toIso8601String());

  Map<String, dynamic> info;
  try {
    info = await api.getAppUpdate();
  } catch (e) {
    debugPrint('update check failed: $e');
    if (manual && context.mounted) _toast(context, 'Update check failed: $e');
    return;
  }

  final code = (info['version_code'] as num?)?.toInt() ?? 0;
  if (code <= local) {
    if (manual && context.mounted) _toast(context, 'Up to date (build $local)');
    return;
  }
  final force = info['force'] == true;
  if (!manual &&
      !force &&
      int.tryParse(await secureRead(_kDismissed) ?? '') == code) {
    return; // this exact version was dismissed with "Later"
  }
  if (!context.mounted) return;

  final notes = '${info['notes'] ?? ''}'.trim();
  final go = await showDialog<bool>(
    context: context,
    barrierDismissible: !force,
    builder: (ctx) => AlertDialog(
      title: const Text('Update available'),
      content: Text('Receipt Tools ${info['version_name']} (build $code)\n'
          'installed: build $local'
          '${notes.isEmpty ? '' : '\n\n$notes'}'),
      actions: [
        if (!force)
          TextButton(
              onPressed: () => Navigator.pop(ctx, false),
              child: const Text('Later')),
        FilledButton(
            onPressed: () => Navigator.pop(ctx, true),
            child: const Text('Update')),
      ],
    ),
  );
  if (go != true) {
    await secureWrite(_kDismissed, '$code');
    return;
  }
  if (!context.mounted) return;
  await performUpdate(context, api, info);
}

void _toast(BuildContext context, String msg) =>
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(msg)));
