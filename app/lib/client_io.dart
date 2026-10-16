import 'dart:io';

import 'package:http/http.dart' as http;
import 'package:http/io_client.dart';

/// Native (mobile/desktop): accept the self-signed Caddy certificate.
http.Client createHttpClient() {
  final h = HttpClient()..badCertificateCallback = (cert, host, port) => true;
  return IOClient(h);
}
