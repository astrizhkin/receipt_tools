import 'dart:convert';
import 'dart:math';

import 'package:device_info_plus/device_info_plus.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';

import 'package:image_picker/image_picker.dart';
import 'package:http/http.dart' as http;
import 'package:http_parser/http_parser.dart';

// Native builds skip the self-signed cert via dart:io HttpClient; web uses
// the browser (direct http://<page-host>:8000, CORS enabled on the pipeline).
import 'client_web.dart' if (dart.library.io) 'client_io.dart';

// flutter_secure_storage_web crashes on write (null-check error); web uses
// localStorage through the same interface instead.
import 'storage_web.dart' if (dart.library.io) 'storage_io.dart';

class ApiException implements Exception {
  final int status;
  final String body;
  ApiException(this.status, this.body);
  @override
  String toString() => 'HTTP $status: $body';
}

/// Server client + account session (device id / PAT in secure storage).
class ApiClient {
  static const _kDevice = 'device_id';
  static const _kPat = 'pat';
  static const _kServer = 'server_url';

  // native helper channel (see MainActivity.kt); ANDROID_ID is not
  // obtainable through device_info_plus
  static const _deviceChannel = MethodChannel('receipt_tools/device');

  static Future<String?> readServerUrl() => secureRead(_kServer);
  static Future<void> writeServerUrl(String url) => secureWrite(_kServer, url);

  final Uri base; // https://host:8000 (app) or /api/ (web, same-origin proxy)
  String deviceId = '';
  String? pat;

  final http.Client _client = createHttpClient();

  ApiClient(this.base);

  /// Random UUID v4 (web fallback identity; also used if a hardware id
  /// lookup fails on native).
  static String _newGuid() {
    final rnd = Random.secure();
    String hex(int n) => List.generate(
        n, (_) => rnd.nextInt(256).toRadixString(16).padLeft(2, '0')).join();
    final b = hex(16).split('');
    b[12] = '4'; // version 4
    b[16] = ((int.parse(b[16], radix: 16) & 0x3) | 0x8).toRadixString(16);
    final s = b.join();
    return '${s.substring(0, 8)}-${s.substring(8, 12)}-'
        '${s.substring(12, 16)}-${s.substring(16, 20)}-${s.substring(20)}';
  }

  Uri _uri(String path) {
    if (base.host.isEmpty) {
      // web: relative base like /api/ -> /api/requests (same-origin proxy)
      final p = base.path;
      return Uri.parse('${p.endsWith('/') ? p.substring(0, p.length - 1) : p}$path');
    }
    return base.resolve(path);
  }

  Map<String, String> get authHeaders => {
        'X-PAT': pat ?? '',
        'X-Device-Id': deviceId,
      };

  /// On launch: load device id + stored pat (may be null), call
  /// /check_account, store the returned pat.
  ///
  /// Device identity (per platform, unique PER DEVICE):
  /// - Android: Settings.Secure.ANDROID_ID via the native device channel —
  ///   device_info_plus CANNOT provide it (androidId was cut from the method
  ///   channel in v4.0.0; the old code used `androidInfo.id`, the firmware
  ///   BUILD id, identical on every phone of one build, which collapsed all
  ///   devices into a single account).
  /// - iOS: identifierForVendor. Linux: machineId.
  /// - Web: no device UID exists, so generate a UUID v4 once and persist it
  ///   (localStorage via the storage shim — stable per browser+site).
  /// A platform prefix keeps ids readable and collision-free across
  /// platforms. The resolved id is cached in secure storage so a failed
  /// lookup later reuses the last known identity instead of forking the
  /// account; a live hardware id always wins over the cache.
  Future<String> _deviceIdentifier() async {
    if (!kIsWeb) {
      try {
        String? hw;
        switch (defaultTargetPlatform) {
          case TargetPlatform.android:
            final id = await _deviceChannel.invokeMethod<String>('androidId');
            if (id != null && id.isNotEmpty) hw = 'and-$id';
          case TargetPlatform.iOS:
            final id = (await DeviceInfoPlugin().iosInfo).identifierForVendor;
            if (id != null && id.isNotEmpty) hw = 'ios-$id';
          case TargetPlatform.linux:
            final id = (await DeviceInfoPlugin().linuxInfo).machineId;
            if (id != null && id.isNotEmpty) hw = 'lin-$id';
          default:
            break;
        }
        if (hw != null) {
          await secureWrite(_kDevice, hw);
          return hw;
        }
      } catch (e) {
        debugPrint('device id: hardware lookup failed ($e); '
            'falling back to stored id');
      }
    }
    final stored = await secureRead(_kDevice);
    if (stored != null) return stored;
    final id = _newGuid();
    await secureWrite(_kDevice, id);
    return id;
  }

  Future<void> bootstrap() async {
    deviceId = await _deviceIdentifier();
    final storedPat = await secureRead(_kPat);
    pat = storedPat;
    debugPrint('auth: device=$deviceId '
        'pat=${storedPat == null ? "none" : "${storedPat.substring(0, 6)}…"}');

    final resp = await _client
        .post(
          _uri('/check_account'),
          headers: {'Content-Type': 'application/json'},
          body: jsonEncode({'device_id': deviceId, 'pat': pat}),
        )
        .timeout(const Duration(seconds: 15));
    if (resp.statusCode != 200) throw ApiException(resp.statusCode, resp.body);

    final j = jsonDecode(resp.body);
    final newPat = j['pat'] as String;
    pat = newPat;
    await secureWrite(_kPat, newPat);
    debugPrint('auth: server -> account_id=${j['account_id']} '
        'is_new=${j['is_new']} pat=$pat');
  }

  /// Version manifest for the self-distributed APK (no auth needed).
  Future<Map<String, dynamic>> getAppUpdate() async =>
      _json(await _client.get(_uri('/app_update'))
          .timeout(const Duration(seconds: 15)));

  /// Absolute URL for a server-relative path (update download; native only).
  Uri absoluteUri(String path) => _uri(path);

  /// Shared client so the native update downloader reuses the same
  /// (cert-bypassing) transport as the API calls.
  http.Client get client => _client;

  Future<Map<String, dynamic>> listRequests() async =>
      _json(await _client.get(_uri('/requests'), headers: authHeaders)
          .timeout(const Duration(seconds: 15)));

  Future<Map<String, dynamic>> getRequest(int id) async =>
      _json(await _client.get(_uri('/requests/$id'), headers: authHeaders)
          .timeout(const Duration(seconds: 15)));

  Future<Map<String, dynamic>> getReceipt(int id) async =>
      _json(await _client.get(_uri('/receipts/$id'), headers: authHeaders)
          .timeout(const Duration(seconds: 15)));

  /// Multipart upload; returns {request_id, status, run_id}.
  /// Bytes (not fromPath): MultipartFile.fromPath is dart:io-only and throws
  /// on web; XFile.readAsBytes works on both platforms.
  Future<Map<String, dynamic>> uploadPhoto(XFile shot) async {
    final bytes = await shot.readAsBytes();
    final name = shot.name;
    final req = http.MultipartRequest('POST', _uri('/photo_input'))
      ..headers.addAll(authHeaders)
      ..files.add(http.MultipartFile.fromBytes(
        'file',
        bytes,
        filename: name,
        contentType: MediaType('image', name.endsWith('.png') ? 'png' : 'jpeg'),
      ));
    final streamed =
        await _client.send(req).timeout(const Duration(minutes: 2));
    final body = await streamed.stream.bytesToString();
    if (streamed.statusCode != 202) {
      throw ApiException(streamed.statusCode, body);
    }
    return jsonDecode(body);
  }

  Map<String, dynamic> _json(http.Response resp) {
    if (resp.statusCode != 200) throw ApiException(resp.statusCode, resp.body);
    return jsonDecode(resp.body);
  }
}
