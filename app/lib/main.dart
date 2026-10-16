import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:image_picker/image_picker.dart';

import 'api.dart';
import 'receipt_page.dart';
import 'settings_page.dart';
import 'update_check.dart';

void main() => runApp(const PriceHunterApp());

class PriceHunterApp extends StatelessWidget {
  const PriceHunterApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Receipt Tools',
      theme: ThemeData(colorSchemeSeed: Colors.deepOrange, useMaterial3: true),
      home: const RequestsScreen(),
    );
  }
}

class RequestsScreen extends StatefulWidget {
  const RequestsScreen({super.key});

  @override
  State<RequestsScreen> createState() => _RequestsScreenState();
}

class _RequestsScreenState extends State<RequestsScreen> {
  // Native: self-signed Caddy TLS (cert check skipped in client_io.dart).
  // Web: same host that served the page, port 8000 (pipeline direct; CORS is
  // enabled there). A manual "/api/" URL still works via the nginx proxy.
  static final String _defaultUrl =
      kIsWeb ? _webDefaultUrl() : 'https://185.80.130.48:8000';

  static String _webDefaultUrl() {
    final page = Uri.base; // e.g. http://192.168.11.24:8090/
    final host = page.host;
    if (host.isEmpty) return '/api/';
    final scheme = page.scheme.isEmpty ? 'http' : page.scheme;
    return '$scheme://$host:8000';
  }

  String _serverUrl = _defaultUrl;
  ApiClient? _api;
  List<dynamic> _requests = [];
  String _error = '';
  bool _busy = false;
  Timer? _timer;

  @override
  void initState() {
    super.initState();
    ApiClient.readServerUrl().then((url) {
      _serverUrl = url ?? _defaultUrl;
      _bootstrap();
    });
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  Future<void> _bootstrap() async {
    setState(() {
      _busy = true;
      _error = '';
    });
    try {
      final api = ApiClient(Uri.parse(_serverUrl));
      await api.bootstrap();
      _api = api;
      await _refresh();
      _timer?.cancel();
      _timer = Timer.periodic(const Duration(seconds: 5), (_) => _refresh());
      // fire-and-forget; self-throttled to once per 24 h (native only)
      if (!kIsWeb) checkForUpdate(context, api);
    } catch (e) {
      debugPrint('bootstrap failed: $e');
      setState(() => _error = 'Server unreachable: $e');
    } finally {
      setState(() => _busy = false);
    }
  }

  Future<void> _refresh() async {
    final api = _api;
    if (api == null) return;
    try {
      final r = await api.listRequests();
      setState(() {
        _requests = r['requests'] as List;
        _error = '';
      });
    } catch (e) {
      debugPrint('refresh failed: $e');
      setState(() => _error = '$e');
    }
  }

  Future<void> _takePhoto() async {
    final api = _api;
    if (api == null) return;
    final shot = await ImagePicker().pickImage(
      source: kIsWeb ? ImageSource.gallery : ImageSource.camera,
      imageQuality: 95,
    );
    if (shot == null) return;
    setState(() => _busy = true);
    try {
      await api.uploadPhoto(shot);
      await _refresh();
    } catch (e) {
      debugPrint('upload failed: $e');
      setState(() => _error = 'Upload failed: $e');
    } finally {
      setState(() => _busy = false);
    }
  }

  String _subtitle(Map r) {
    final dur = r['duration_s'];
    switch (r['status']) {
      case 'queued':
        return 'queued';
      case 'running':
        return 'running: ${r['stage']} — ${dur ?? 0}s';
      case 'failed':
        return 'failed: ${r['error'] ?? 'unknown error'}';
      default:
        return 'completed — ${dur ?? '?'}s';
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Receipt Tools'),
        actions: [
          IconButton(
            icon: const Icon(Icons.refresh),
            onPressed: _api == null ? _bootstrap : _refresh,
          ),
          IconButton(
            icon: const Icon(Icons.settings),
            onPressed: () => Navigator.push(
              context,
              MaterialPageRoute(
                builder: (_) => SettingsPage(
                  api: _api,
                  serverUrl: _serverUrl,
                  onSaved: (url) {
                    // SettingsPage already persisted the url.
                    setState(() => _serverUrl = url);
                    _bootstrap();
                  },
                ),
              ),
            ),
          ),
        ],
      ),
      body: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          if (_error.isNotEmpty)
            Padding(
              padding: const EdgeInsets.all(8),
              child: Text(_error,
                  style: const TextStyle(color: Colors.redAccent)),
            ),
          Expanded(
            child: _requests.isEmpty
                ? const Center(child: Text('No requests yet — take a photo!'))
                : ListView.separated(
                    itemCount: _requests.length,
                    separatorBuilder: (_, __) => const Divider(height: 1),
                    itemBuilder: (context, i) {
                      final r = _requests[i] as Map;
                      final done = r['status'] == 'completed' &&
                          r['receipt_id'] != null;
                      return ListTile(
                        title: Text(r['store_name'] != null
                            ? '${r['store_name']}'
                            : 'Request #${r['id']}'),
                        subtitle: Text(_subtitle(r)),
                        trailing: done
                            ? const Icon(Icons.chevron_right)
                            : _statusChip(r['status'] as String),
                        onTap: done
                            ? () => Navigator.push(
                                  context,
                                  MaterialPageRoute(
                                    builder: (_) => ReceiptPage(
                                      api: _api!,
                                      receiptId: r['receipt_id'] as int,
                                      title: '${r['store_name'] ?? ''}',
                                    ),
                                  ),
                                )
                            : null,
                      );
                    },
                  ),
          ),
        ],
      ),
      floatingActionButton: FloatingActionButton.extended(
        onPressed: (_busy || _api == null) ? null : _takePhoto,
        icon: _busy
            ? const CircularProgressIndicator(color: Colors.white)
            : Icon(kIsWeb ? Icons.upload_file : Icons.photo_camera),
        label: Text(_busy
            ? 'Working…'
            : (kIsWeb ? 'Upload a photo' : 'Take a photo')),
      ),
    );
  }

  Widget _statusChip(String status) {
    final color = switch (status) {
      'completed' => Colors.green,
      'failed' => Colors.red,
      'running' => Colors.orange,
      _ => Colors.grey,
    };
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
      decoration: BoxDecoration(color: color.withValues(alpha: 0.15)),
      child: Text(status, style: TextStyle(color: color, fontSize: 12)),
    );
  }
}
