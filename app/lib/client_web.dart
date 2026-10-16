import 'package:http/http.dart' as http;

/// Web: browser handles TLS (accept the cert once in the browser, or use the
/// same-origin /api proxy served by nginx).
http.Client createHttpClient() => http.Client();
