import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:package_info_plus/package_info_plus.dart';

import 'api.dart';
import 'update_check.dart';

class SettingsPage extends StatefulWidget {
  final ApiClient? api;
  final String serverUrl;
  final void Function(String url) onSaved;

  const SettingsPage({
    super.key,
    required this.api,
    required this.serverUrl,
    required this.onSaved,
  });

  @override
  State<SettingsPage> createState() => _SettingsPageState();
}

class _SettingsPageState extends State<SettingsPage> {
  late final TextEditingController _urlCtrl =
      TextEditingController(text: widget.serverUrl);
  bool _showPat = false;
  String _version = '';

  @override
  void initState() {
    super.initState();
    if (!kIsWeb) {
      PackageInfo.fromPlatform().then((p) =>
          setState(() => _version = '${p.version}+${p.buildNumber}'));
    }
  }

  @override
  void dispose() {
    _urlCtrl.dispose();
    super.dispose();
  }

  Future<void> _save() async {
    final url = _urlCtrl.text.trim();
    if (url.isEmpty) return;
    try {
      await ApiClient.writeServerUrl(url);
    } catch (e) {
      debugPrint('server url save failed: $e');
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text('Save failed: $e')));
      }
      return;
    }
    widget.onSaved(url);
    if (mounted) {
      ScaffoldMessenger.of(context)
          .showSnackBar(const SnackBar(content: Text('Server saved, reconnecting…')));
    }
  }

  Widget _copyButton(String? value) => IconButton(
        icon: const Icon(Icons.copy, size: 18),
        onPressed: value == null
            ? null
            : () {
                Clipboard.setData(ClipboardData(text: value));
                ScaffoldMessenger.of(context).showSnackBar(
                    const SnackBar(content: Text('Copied')));
              },
      );

  @override
  Widget build(BuildContext context) {
    final api = widget.api;
    final pat = api?.pat;
    final shownPat = pat == null
        ? '—'
        : _showPat
            ? pat
            : '${pat.substring(0, 6)}…${pat.substring(pat.length - 4)}';
    return Scaffold(
      appBar: AppBar(title: const Text('Settings')),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          const Text('Server endpoint',
              style: TextStyle(fontWeight: FontWeight.w600)),
          const SizedBox(height: 8),
          Row(
            children: [
              Expanded(
                child: TextField(
                  controller: _urlCtrl,
                  decoration: const InputDecoration(
                    border: OutlineInputBorder(),
                    isDense: true,
                  ),
                ),
              ),
              const SizedBox(width: 8),
              FilledButton(onPressed: _save, child: const Text('Save')),
            ],
          ),
          const Divider(height: 32),
          ListTile(
            contentPadding: EdgeInsets.zero,
            title: const Text('Device id', style: TextStyle(fontWeight: FontWeight.w600)),
            subtitle: SelectableText(api?.deviceId ?? '— (not connected)'),
            trailing: _copyButton(api?.deviceId),
          ),
          const Divider(),
          if (!kIsWeb)
            ListTile(
              contentPadding: EdgeInsets.zero,
              title: const Text('Check for update',
                  style: TextStyle(fontWeight: FontWeight.w600)),
              subtitle: Text(_version.isEmpty ? 'version…' : 'installed: $_version'),
              trailing: IconButton(
                icon: const Icon(Icons.system_update, size: 20),
                onPressed: widget.api == null
                    ? null
                    : () => checkForUpdate(context, widget.api!, manual: true),
              ),
            ),
          if (!kIsWeb) const Divider(),
          ListTile(
            contentPadding: EdgeInsets.zero,
            title: const Text('Access token (PAT)',
                style: TextStyle(fontWeight: FontWeight.w600)),
            subtitle: SelectableText(shownPat),
            trailing: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                IconButton(
                  icon: Icon(_showPat ? Icons.visibility_off : Icons.visibility,
                      size: 18),
                  onPressed: () => setState(() => _showPat = !_showPat),
                ),
                _copyButton(pat),
              ],
            ),
          ),
        ],
      ),
    );
  }
}
