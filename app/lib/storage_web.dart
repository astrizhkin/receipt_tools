import 'package:web/web.dart' as web;

// Web: flutter_secure_storage_web throws "Null check operator used on null
// value" on write, so use localStorage directly (fine for a demo PAT).
Future<String?> secureRead(String key) async {
  try {
    return web.window.localStorage.getItem(key);
  } catch (_) {
    return null;
  }
}

Future<void> secureWrite(String key, String value) async {
  try {
    web.window.localStorage.setItem(key, value);
  } catch (_) {
    // Private-mode/blocked storage: keep running with an in-memory session.
  }
}
