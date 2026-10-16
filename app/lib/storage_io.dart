import 'package:flutter_secure_storage/flutter_secure_storage.dart';

// Native (Android/iOS): encrypted shared prefs / keychain via the plugin.
const _storage = FlutterSecureStorage();

Future<String?> secureRead(String key) => _storage.read(key: key);

Future<void> secureWrite(String key, String value) =>
    _storage.write(key: key, value: value);
