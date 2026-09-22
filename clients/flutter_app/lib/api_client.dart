import 'dart:async';
import 'dart:convert';
import 'dart:io';

class ApiFailure implements Exception {
  final String code;
  final int? status;
  const ApiFailure(this.code, [this.status]);
  @override
  String toString() => code;
}

/// Shared native transport; tokens and business responses remain in memory.
class ApiClient {
  final Uri server;
  final HttpClient _http = HttpClient();
  final void Function()? onSessionCleared;
  String? _token;
  int _generation = 0;
  bool _closed = false;

  ApiClient(String address, {this.onSessionCleared}) : server = validateServer(address) {
    _http.connectionTimeout = const Duration(seconds: 15);
    // Platform TLS verification; never set badCertificateCallback.
  }

  static Uri validateServer(String address) {
    final uri = Uri.tryParse(address.trim());
    if (uri == null || uri.scheme != 'https' || uri.host.isEmpty ||
        uri.userInfo.isNotEmpty || uri.hasQuery || uri.hasFragment ||
        (uri.path.isNotEmpty && uri.path != '/')) {
      throw const ApiFailure('INVALID_HTTPS_SERVER');
    }
    return uri;
  }

  bool get authenticated => _token != null && !_closed;
  void clearSession() {
    _token = null;
    _generation++;
    onSessionCleared?.call();
  }

  Future<Map<String, dynamic>> login(String username, String password) async {
    clearSession();
    final generation = _generation;
    final result = await _perform('POST', ['auth', 'login'], body: {
      'username': username, 'password': password,
    });
    _checkGeneration(generation);
    if (result is! Map<String, dynamic> || result['access_token'] is! String ||
        (result['access_token'] as String).length < 20 || result['token_type'] != 'bearer') {
      throw const ApiFailure('INVALID_RESPONSE');
    }
    _token = result['access_token'] as String;
    try {
      final person = await request('GET', ['me']);
      if (person is! Map<String, dynamic>) throw const ApiFailure('INVALID_RESPONSE');
      return person;
    } catch (_) {
      if (_generation == generation) clearSession();
      rethrow;
    }
  }

  Future<void> logout() async {
    final previous = _token;
    clearSession(); // Local cleanup is immediate even if the server is offline.
    if (previous != null) await _perform('POST', ['auth', 'logout'], token: previous);
  }

  Future<dynamic> request(String method, List<String> segments,
      {Map<String, dynamic>? body, Map<String, String>? query,
       List<int>? uploadBytes, String? uploadFormat}) async {
    if (!authenticated) throw const ApiFailure('AUTHENTICATION_REQUIRED', 401);
    final generation = _generation;
    try {
      final result = await _perform(method, segments, body: body, query: query, token: _token,
          uploadBytes: uploadBytes, uploadFormat: uploadFormat);
      _checkGeneration(generation);
      return result;
    } on ApiFailure catch (error) {
      if (error.status == 401 && _generation == generation) clearSession();
      rethrow;
    }
  }

  /// The server owns labels and publication; local file paths are never transmitted.
  Future<dynamic> uploadDocument(String documentId, int expectedVersion,
      String format, List<int> bytes, {String equipmentId = ''}) {
    if (expectedVersion < 1 || !['txt', 'pdf'].contains(format) ||
        bytes.isEmpty || bytes.length > 10 * 1024 * 1024) {
      throw const ApiFailure('INVALID_UPLOAD');
    }
    return request('POST', ['admin', 'documents', documentId, 'content'], query: {
      'expected_version': '$expectedVersion', 'format': format,
      if (equipmentId.isNotEmpty) 'equipment_id': equipmentId,
    }, uploadBytes: List<int>.unmodifiable(bytes), uploadFormat: format);
  }

  void _checkGeneration(int generation) {
    if (_closed || generation != _generation) throw const ApiFailure('STALE_SESSION_RESPONSE');
  }

  Future<dynamic> _perform(String method, List<String> segments,
      {Map<String, dynamic>? body, Map<String, String>? query, String? token,
       List<int>? uploadBytes, String? uploadFormat}) async {
    if (_closed) throw const ApiFailure('CLIENT_CLOSED');
    if (!['GET', 'POST', 'PATCH'].contains(method) ||
        segments.any((s) => s.isEmpty || s == '.' || s == '..' || s.contains('/') || s.contains('\\'))) {
      throw const ApiFailure('INVALID_REQUEST');
    }
    if (uploadBytes != null && (body != null || method != 'POST' ||
        !['txt', 'pdf'].contains(uploadFormat) || uploadBytes.isEmpty ||
        uploadBytes.length > 10 * 1024 * 1024)) {
      throw const ApiFailure('INVALID_UPLOAD');
    }
    final uri = server.replace(pathSegments: ['api', 'v1', ...segments], queryParameters: query);
    HttpClientRequest? active;
    Future<dynamic> exchange() async {
      final outgoing = await _http.openUrl(method, uri);
      active = outgoing;
      outgoing.followRedirects = false;
      outgoing.headers.set(HttpHeaders.acceptHeader, 'application/json');
      if (token != null) outgoing.headers.set(HttpHeaders.authorizationHeader, 'Bearer $token');
      if (uploadBytes != null) {
        outgoing.headers.contentType = uploadFormat == 'pdf'
            ? ContentType('application', 'pdf') : ContentType('text', 'plain', charset: 'utf-8');
        outgoing.contentLength = uploadBytes.length;
        outgoing.add(uploadBytes);
      } else if (body != null) {
        outgoing.headers.contentType = ContentType.json;
        outgoing.write(jsonEncode(body));
      }
      final response = await outgoing.close();
      final bytes = <int>[];
      await for (final part in response) {
        if (bytes.length + part.length > 2 * 1024 * 1024) {
          outgoing.abort();
          throw const ApiFailure('RESPONSE_TOO_LARGE');
        }
        bytes.addAll(part);
      }
      if (response.statusCode < 200 || response.statusCode >= 300) {
        throw ApiFailure('HTTP_${response.statusCode}', response.statusCode);
      }
      return jsonDecode(utf8.decode(bytes));
    }
    try {
      return await exchange().timeout(const Duration(seconds: 150), onTimeout: () {
        active?.abort();
        throw const ApiFailure('REQUEST_TIMEOUT');
      });
    } on ApiFailure {
      rethrow;
    } catch (_) {
      throw const ApiFailure('NETWORK_OR_RESPONSE_ERROR');
    }
  }

  void close() {
    _closed = true;
    clearSession();
    _http.close(force: true);
  }
}
