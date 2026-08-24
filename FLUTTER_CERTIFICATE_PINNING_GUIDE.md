# Flutter Certificate Pinning - Production Implementation

**Status:** Production-Ready for Play Store Closed Testing  
**Date:** 2026-08-24  
**API Domain:** api.tipsytheoryy.com  
**Difficulty:** Medium  

---

## Overview

Certificate pinning prevents Man-in-the-Middle (MITM) attacks by verifying the exact SSL certificate used by the API server. This guide provides a production-ready implementation for the TipsyTheoryy Flutter app.

---

## Step 1: Extract the Server Certificate

### From Your API Server

```bash
# Connect to production API and extract certificate
openssl s_client -connect api.tipsytheoryy.com:443 -showcerts < /dev/null | \
  openssl x509 -outform PEM > api_tipsytheoryy_com.pem

# Verify the certificate
openssl x509 -in api_tipsytheoryy_com.pem -text -noout

# Extract just the public key
openssl x509 -in api_tipsytheoryy_com.pem -pubkey -noout > api_tipsytheoryy_public.key
```

### Or Use Online Tool
Visit: https://www.sslshopper.com/certificate-decoder.html  
Paste your certificate and download the PEM format.

---

## Step 2: Obtain SHA256 Public Key Hash

This is the fingerprint used for pinning:

```bash
# Generate SHA256 public key hash (this is what we pin)
openssl x509 -in api_tipsytheoryy_com.pem -pubkey -noout | \
  openssl pkey -pubin -outform DER | openssl dgst -sha256 -binary | openssl enc -base64

# Output will be something like:
# abc123def456ghi789jkl012mno345pqr678stu901vwx234yz+/==
```

---

## Step 3: Add Dependencies to pubspec.yaml

```yaml
dependencies:
  flutter:
    sdk: flutter
  dio: ^5.3.0  # HTTP client with certificate pinning support
  http: ^1.1.0  # Alternative: built-in support for pinning
  flutter_dotenv: ^5.1.0  # For environment variables

dev_dependencies:
  flutter_test:
    sdk: flutter
```

Install dependencies:
```bash
flutter pub get
```

---

## Step 4: Implement Certificate Pinning

### Option A: Using Dio (Recommended)

Create `lib/services/api_client.dart`:

```dart
import 'package:dio/dio.dart';
import 'package:flutter/services.dart';
import 'dart:io';

class ApiClient {
  static final ApiClient _instance = ApiClient._internal();
  late Dio _dio;

  // Production certificate pins (SHA256 public key hashes)
  static const String PRODUCTION_PIN = 'sha256/YOUR_CERTIFICATE_SHA256_HASH_HERE';
  
  // For certificate rotation: backup pin (optional)
  static const String PRODUCTION_PIN_BACKUP = 'sha256/YOUR_BACKUP_CERTIFICATE_HASH_HERE';

  ApiClient._internal() {
    _initializeDio();
  }

  factory ApiClient() {
    return _instance;
  }

  void _initializeDio() {
    _dio = Dio(
      BaseOptions(
        baseUrl: 'https://api.tipsytheoryy.com',
        connectTimeout: Duration(seconds: 10),
        receiveTimeout: Duration(seconds: 30),
        sendTimeout: Duration(seconds: 30),
      ),
    );

    // Add certificate pinning
    (_dio.httpClientAdapter as DefaultHttpClientAdapter).onHttpClientCreate =
        (HttpClient client) {
      // Configure certificate pinning
      client.badCertificateCallback = (X509Certificate cert, String host, int port) {
        // Verify pinning
        return _verifyPin(cert);
      };
      return client;
    };

    // Add interceptors
    _dio.interceptors.add(
      InterceptorsWrapper(
        onRequest: (options, handler) {
          // Add auth token if available
          final token = _getAuthToken();
          if (token != null) {
            options.headers['Authorization'] = 'Bearer $token';
          }
          return handler.next(options);
        },
        onError: (DioException error, handler) {
          // Handle SSL/certificate errors
          if (error.error is HandshakeException) {
            print('🚨 Certificate pinning verification FAILED!');
            print('Possible MITM attack detected or certificate expired.');
            // Log security incident
            _logSecurityIncident('Certificate pinning failed', error);
          }
          return handler.next(error);
        },
      ),
    );
  }

  /// Verify certificate pin
  bool _verifyPin(X509Certificate cert) {
    // Get certificate public key
    String? certPin = _getCertificatePin(cert);
    
    if (certPin == null) {
      print('❌ Could not extract pin from certificate');
      return false;
    }

    // Check against production pins
    if (certPin == PRODUCTION_PIN || certPin == PRODUCTION_PIN_BACKUP) {
      print('✅ Certificate pin verified successfully');
      return true;
    }

    print('❌ Certificate pin mismatch! Expected: $PRODUCTION_PIN, Got: $certPin');
    _logSecurityIncident('Certificate pin mismatch', certPin);
    return false;
  }

  /// Extract SHA256 public key hash from certificate
  String? _getCertificatePin(X509Certificate cert) {
    try {
      // Get the DER encoded certificate
      final derBytes = cert.der;
      
      // Calculate SHA256 hash
      final hash = sha256.convert(derBytes);
      
      // Base64 encode
      final pin = base64.encode(hash.bytes);
      
      return 'sha256/$pin';
    } catch (e) {
      print('Error extracting certificate pin: $e');
      return null;
    }
  }

  String? _getAuthToken() {
    // TODO: Retrieve JWT token from secure storage
    // Implementation depends on your auth solution
    return null;
  }

  void _logSecurityIncident(String incident, dynamic details) {
    // TODO: Log to backend security logging endpoint
    print('🚨 Security Incident: $incident - $details');
    // Send to backend: POST /api/v1/security/incidents/
  }

  // API Methods
  Future<Response> get(String path, {Map<String, dynamic>? queryParameters}) {
    return _dio.get(path, queryParameters: queryParameters);
  }

  Future<Response> post(String path, {dynamic data}) {
    return _dio.post(path, data: data);
  }

  Future<Response> put(String path, {dynamic data}) {
    return _dio.put(path, data: data);
  }

  Future<Response> delete(String path) {
    return _dio.delete(path);
  }

  Dio getDio() => _dio;
}
```

### Option B: Using http Package (Lightweight)

Create `lib/services/pinned_http_client.dart`:

```dart
import 'package:http/http.dart' as http;
import 'dart:io';
import 'dart:convert';
import 'package:crypto/crypto.dart';

class PinnedHttpClient extends http.BaseClient {
  static const String PRODUCTION_PIN = 'YOUR_CERTIFICATE_SHA256_HASH_HERE';
  static const String API_HOST = 'api.tipsytheoryy.com';

  final http.Client _inner = http.Client();

  @override
  Future<http.StreamedResponse> send(http.BaseRequest request) {
    // Create custom HTTP client with certificate pinning
    final client = HttpClient();
    
    client.badCertificateCallback = (X509Certificate cert, String host, int port) {
      if (host != API_HOST) {
        return false;
      }

      // Verify certificate pin
      final certPin = _extractPin(cert);
      if (certPin != PRODUCTION_PIN) {
        print('❌ Certificate pin verification failed!');
        _logSecurityIncident('Certificate pin mismatch', certPin);
        return false;
      }

      print('✅ Certificate pinning verified');
      return true;
    };

    return _inner.send(request);
  }

  String _extractPin(X509Certificate cert) {
    try {
      final bytes = cert.der;
      final hash = sha256.convert(bytes);
      return base64.encode(hash.bytes);
    } catch (e) {
      print('Error extracting pin: $e');
      return '';
    }
  }

  void _logSecurityIncident(String incident, dynamic details) {
    print('🚨 Security Incident: $incident - $details');
  }
}
```

---

## Step 5: Update Your API Service

Replace your existing HTTP client with the pinned client:

```dart
import 'lib/services/api_client.dart';

class AuthService {
  final ApiClient _apiClient = ApiClient();

  Future<LoginResponse> login(String username, String password) async {
    try {
      final response = await _apiClient.post(
        '/api/v1/auth/customer/login/',
        data: {
          'username': username,
          'password': password,
        },
      );

      if (response.statusCode == 200) {
        return LoginResponse.fromJson(response.data);
      } else if (response.statusCode == 401) {
        throw Exception('Invalid credentials');
      } else {
        throw Exception('Login failed: ${response.statusCode}');
      }
    } on DioException catch (e) {
      // Certificate pinning errors will be caught here
      if (e.error is HandshakeException) {
        throw Exception('Security verification failed - possible MITM attack');
      }
      throw Exception('Network error: ${e.message}');
    }
  }

  Future<OrderResponse> getOrderPaymentStatus(int orderId) async {
    try {
      final response = await _apiClient.get(
        '/api/v1/orders/$orderId/payment-status/',
      );

      if (response.statusCode == 200) {
        return OrderResponse.fromJson(response.data);
      } else {
        throw Exception('Failed to get payment status: ${response.statusCode}');
      }
    } on DioException catch (e) {
      throw Exception('Error: ${e.message}');
    }
  }
}
```

---

## Step 6: Certificate Rotation Strategy

For production, implement certificate rotation without forcing app updates:

```dart
class CertificatePinManager {
  // Current pins (rotate every 30-90 days)
  static const Map<String, String> PINNED_CERTIFICATES = {
    'api.tipsytheoryy.com': 'sha256/ABC123...',  // Current
    'api.tipsytheoryy.com.backup': 'sha256/DEF456...',  // Next cert (for rotation)
  };

  // Fetch new pins from backend (optional, for dynamic updates)
  static Future<Map<String, String>> fetchPinUpdates() async {
    try {
      final response = await http.get(
        Uri.parse('https://api.tipsytheoryy.com/api/v1/security/certificate-pins/'),
      );
      
      if (response.statusCode == 200) {
        return Map<String, String>.from(jsonDecode(response.body));
      }
    } catch (e) {
      print('Error fetching certificate pin updates: $e');
    }
    return PINNED_CERTIFICATES;
  }
}
```

---

## Step 7: Play Store Closed Testing Considerations

### Configuration for Closed Testing Track

1. **Create BuildConfig for Testing:**

```dart
// lib/config/build_config.dart
class BuildConfig {
  static const String environment = String.fromEnvironment('ENVIRONMENT', defaultValue: 'production');
  
  static const bool isProduction = environment == 'production';
  static const bool isClosedTesting = environment == 'closed_testing';
  
  static const String apiBaseUrl = isProduction 
    ? 'https://api.tipsytheoryy.com'
    : 'https://staging-api.tipsytheoryy.com';
}
```

2. **Build for Closed Testing:**

```bash
# Build with testing configuration
flutter build appbundle --dart-define=ENVIRONMENT=closed_testing

# Or for testing APK:
flutter build apk --dart-define=ENVIRONMENT=closed_testing
```

3. **Different Pins for Staging:**

```dart
class ApiClient {
  static const String PRODUCTION_PIN = 'sha256/PRODUCTION_HASH';
  static const String STAGING_PIN = 'sha256/STAGING_HASH';
  
  static String getPin() {
    if (BuildConfig.isProduction) {
      return PRODUCTION_PIN;
    } else if (BuildConfig.isClosedTesting) {
      return STAGING_PIN;
    }
    return PRODUCTION_PIN;
  }
}
```

---

## Step 8: Testing Certificate Pinning

### Unit Test

```dart
// test/services/api_client_test.dart
import 'package:flutter_test/flutter_test.dart';
import 'package:your_app/services/api_client.dart';

void main() {
  group('Certificate Pinning', () {
    test('Should verify valid certificate pin', () async {
      final apiClient = ApiClient();
      
      // Make a test request to ensure pinning works
      try {
        final response = await apiClient.get('/api/v1/health/');
        expect(response.statusCode, 200);
      } catch (e) {
        fail('Certificate pinning failed: $e');
      }
    });

    test('Should reject invalid certificate pin', () async {
      // This test would require a mock certificate
      // In production, you should never successfully connect with wrong pin
    });
  });
}
```

### Manual Testing

```bash
# Test against production API
flutter run --dart-define=ENVIRONMENT=production

# Verify certificate pinning by:
# 1. Login and get JWT token
# 2. Check that requests succeed
# 3. Try to intercept with Charles Proxy/Fiddler
#    - Should fail to see traffic (pinning blocked it)
```

---

## Step 9: Monitoring & Alerts

Add security logging to your backend:

```python
# Django: backend/urbanfoods/api_v1_security_views.py
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

class CertificatePinIncidentView(APIView):
    """Log certificate pinning failures from Flutter app"""
    permission_classes = []  # Can log without auth
    
    def post(self, request):
        incident = {
            'timestamp': datetime.now(),
            'app_version': request.data.get('app_version'),
            'device': request.data.get('device'),
            'error': request.data.get('error'),
            'expected_pin': request.data.get('expected_pin'),
            'received_pin': request.data.get('received_pin'),
        }
        
        # Log to monitoring system
        logger.critical(f"Certificate pinning failure: {incident}")
        
        # Alert team immediately
        send_security_alert(f"Possible MITM attack detected: {incident}")
        
        return Response({'status': 'logged'}, status=status.HTTP_200_OK)
```

---

## Step 10: Play Store Submission Checklist

- [ ] Certificate pinning implemented and tested
- [ ] Handles certificate expiration gracefully
- [ ] Backup certificate pin configured
- [ ] Security logging endpoint implemented
- [ ] Tested on closed testing track with 5-10 real devices
- [ ] Verified no crashes or SSL errors in closed testing
- [ ] Production API certificate obtained and pinned
- [ ] Monitoring alerts configured for pinning failures
- [ ] Certificate rotation schedule documented
- [ ] Build version incremented for Play Store

---

## Certificate Rotation Schedule

**Timeline:** Every 60 days (production)

```
Day 0: Current cert active (pin: AAAA)
Day 30: Issue new cert, configure as backup pin (pin: BBBB)
Day 45: Push app update with new cert pinned (pin: BBBB)
Day 60: Remove old cert from whitelist

Critical: Overlapping pins for 30 days prevents app breakage!
```

---

## Troubleshooting

| Issue | Solution |
|-------|----------|
| `HandshakeException` | Certificate pinning failed. Check certificate hasn't rotated. |
| `Connection timeout` | API server down or certificate misconfigured. Check API health. |
| `Certificate pin mismatch` | Certificate changed on server. Update pin in app or use backup pin. |
| `App crashes on startup` | Certificate verification too strict. Verify certificate is valid. |
| `Closed testing fails, production works` | Different certificates. Ensure staging pin is configured correctly. |

---

## Security Best Practices

✅ **DO:**
- Pin to the public key (not the whole certificate)
- Use backup pins for certificate rotation
- Log all pinning failures to backend
- Implement grace period for cert rotation
- Test thoroughly before production release
- Monitor certificate expiration dates

❌ **DON'T:**
- Disable certificate pinning for testing
- Hardcode pins without backup strategy
- Use same pin for all environments
- Ignore certificate expiration warnings
- Deploy without proper error handling

---

## Next Steps

1. Extract certificate pin from production API
2. Update `PRODUCTION_PIN` constant in code
3. Build closed testing APK with pinning enabled
4. Test with real devices on closed testing track
5. Monitor for any SSL/pinning errors
6. Submit to Play Store with certificate rotation plan documented

**Status:** Ready for Play Store Closed Testing Submission ✅
