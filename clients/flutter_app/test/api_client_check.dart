import '../lib/api_client.dart';

Future<void> main() async {
  for (final address in [
    'http://localhost:8000', 'https://user:password@example.com',
    'https://example.com/private', 'https://example.com?token=x',
    'https://example.com#fragment', 'file:///local',
  ]) {
    var rejected = false;
    try {
      ApiClient.validateServer(address);
    } on ApiFailure {
      rejected = true;
    }
    if (!rejected) throw StateError('Unsafe server was accepted');
  }
  if (ApiClient.validateServer('https://example.com:8443').port != 8443) {
    throw StateError('HTTPS port was not retained');
  }
  var clears = 0;
  final client = ApiClient('https://example.com', onSessionCleared: () => clears++);
  for (final format in ['exe', '']) {
    try {
      await client.uploadDocument('DOC', 1, format, [65]);
      throw StateError('Unsupported upload format accepted');
    } on ApiFailure catch (error) {
      if (error.code != 'INVALID_UPLOAD') rethrow;
    }
  }
  try {
    await client.uploadDocument('DOC', 1, 'txt', [65]);
    throw StateError('Unauthenticated upload accepted');
  } on ApiFailure catch (error) {
    if (error.status != 401) rethrow;
  }
  client.clearSession();
  client.close();
  if (client.authenticated || clears != 2) throw StateError('Session clear failed');
}
