import 'package:flutter/material.dart';

import 'api.dart';

/// Web build: in-app self-update is impossible; never called (kIsWeb guarded).
Future<void> performUpdate(
  BuildContext context,
  ApiClient api,
  Map<String, dynamic> info,
) async =>
    throw UnsupportedError('in-app updates are Android-only');
