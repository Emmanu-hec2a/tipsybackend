# Extract Production Certificate Pin - Quick Guide

**Goal:** Get the SHA256 public key hash from api.tipsytheoryy.com and update the Flutter app

---

## Method 1: Quick Extract (Recommended)

### On Windows (PowerShell)

```powershell
# Install OpenSSL if needed
# choco install openssl

# Step 1: Extract the server certificate
openssl s_client -connect api.tipsytheoryy.com:443 -showcerts < $null | `
  openssl x509 -outform PEM > api_cert.pem

# Step 2: Generate SHA256 public key hash
openssl x509 -in api_cert.pem -pubkey -noout | `
  openssl pkey -pubin -outform DER | openssl dgst -sha256 -binary | openssl enc -base64

# Output: This is your PRODUCTION_PIN
# Copy this value into api_client.dart
```

### On macOS/Linux

```bash
# Step 1: Extract certificate
openssl s_client -connect api.tipsytheoryy.com:443 -showcerts < /dev/null | \
  openssl x509 -outform PEM > api_cert.pem

# Step 2: Generate hash
openssl x509 -in api_cert.pem -pubkey -noout | \
  openssl pkey -pubin -outform DER | openssl dgst -sha256 -binary | openssl enc -base64
```

### Expected Output
```
ABC123DEF456GHI789JKL012MNO345PQR678STU901VWX234YZ+/==
```

---

## Method 2: Using Android Network Security Configuration

Flutter can also use Android's network security configuration:

**android/app/src/main/res/xml/network_security_config.xml**

```xml
<?xml version="1.0" encoding="utf-8"?>
<network-security-config>
    <domain-config cleartextTrafficPermitted="false">
        <domain includeSubdomains="true">api.tipsytheoryy.com</domain>
        <pin-set expiration="2026-12-31">
            <!-- SHA256 public key pins -->
            <pin digest="SHA-256">sha256/YOUR_CERTIFICATE_PIN_HERE</pin>
            <!-- Backup pin for rotation -->
            <pin digest="SHA-256">sha256/YOUR_BACKUP_CERTIFICATE_PIN_HERE</pin>
        </pin-set>
    </domain-config>
</network-security-config>
```

**android/app/src/main/AndroidManifest.xml**

```xml
<application
    android:networkSecurityConfig="@xml/network_security_config">
    ...
</application>
```

---

## Method 3: iOS Certificate Pinning

For iOS, use the same pins in your code (iOS doesn't have XML config):

**ios/Runner/Info.plist**

```xml
<key>AppTransportSecurity</key>
<dict>
    <key>NSExceptionDomains</key>
    <dict>
        <key>api.tipsytheoryy.com</key>
        <dict>
            <key>NSIncludesSubdomains</key>
            <true/>
            <key>NSExceptionMinimumTLSVersion</key>
            <string>TLSv1.2</string>
        </dict>
    </dict>
</dict>
```

**Note:** The actual pinning verification happens in the Dart code (api_client.dart)

---

## Step-by-Step Update Process

### 1. Extract the Pin

```bash
# Run the extraction command from above
openssl x509 -in api_cert.pem -pubkey -noout | \
  openssl pkey -pubin -outform DER | openssl dgst -sha256 -binary | openssl enc -base64

# Result: ABC123DEF456...
```

### 2. Update api_client.dart

```dart
// Replace this:
static const String PRODUCTION_PIN = 'sha256/REPLACE_WITH_YOUR_CERTIFICATE_PIN';

// With this (add your hash):
static const String PRODUCTION_PIN = 'sha256/ABC123DEF456GHI789JKL012MNO345PQR678STU901VWX234YZ+/==';
```

### 3. Update build_config.dart

```dart
static Map<String, String> get certificatePins {
  switch (environment) {
    case 'production':
      return {
        'host': 'api.tipsytheoryy.com',
        'pin': 'sha256/ABC123DEF456GHI789JKL012MNO345PQR678STU901VWX234YZ+/==',  // Your pin
        'backup_pin': 'sha256/DEF456...',  // For rotation
      };
    // ... other environments
  }
}
```

### 4. Verify Certificate Details

```bash
# View certificate info
openssl x509 -in api_cert.pem -text -noout

# Check expiration
openssl x509 -in api_cert.pem -noout -dates

# Output example:
# notBefore=Aug 24 00:00:00 2024 GMT
# notAfter=Aug 23 23:59:59 2025 GMT
```

### 5. Build for Closed Testing

```bash
# Build APK for closed testing
flutter build apk --dart-define=ENVIRONMENT=closed_testing

# Or build bundle for Play Store
flutter build appbundle --dart-define=ENVIRONMENT=production
```

### 6. Test Certificate Pinning

```bash
# Run auth service test
flutter run lib/main_test.dart

# Or use the included test:
# auth_service.testRateLimiting(orderId: 109, requestCount: 35)
```

---

## Certificate Rotation Schedule

**Every 60 days:**

| Day | Action | Pins Status |
|-----|--------|-------------|
| Day 0 | Current cert active | PIN_A only |
| Day 30 | Issue new cert, configure as backup | PIN_A + PIN_B (both active) |
| Day 45 | Push app update with new pin | PIN_B only (old PIN_A removed) |
| Day 60 | Remove old cert from server | PIN_B only |

**Key:** Overlapping pins for 15 days prevents app breakage!

---

## Backup Pin Strategy (Recommended)

Always maintain a backup pin:

```dart
class ApiClient {
  // Primary certificate (current)
  static const String PRODUCTION_PIN = 'sha256/ABC123...';
  
  // Backup certificate (for rotation, configured 30 days before switching)
  static const String PRODUCTION_PIN_BACKUP = 'sha256/DEF456...';
}
```

Then in `_verifyPin()`:

```dart
bool _verifyPin(X509Certificate cert) {
  final certPin = _extractPin(cert);
  
  // Accept either primary or backup
  if (certPin == PRODUCTION_PIN) {
    print('✅ Primary certificate verified');
    return true;
  }
  
  if (certPin == PRODUCTION_PIN_BACKUP) {
    print('✅ Backup certificate verified (rotation in progress)');
    return true;
  }
  
  print('❌ Certificate pin mismatch!');
  return false;
}
```

---

## Certificate Expiration Monitoring

Add to your backend monitoring (Django):

```python
# Check certificate expiration daily
from datetime import datetime, timedelta
import ssl

def check_certificate_expiration():
    cert = ssl.create_default_context().get_ca_certs()
    # Extract expiration date
    # Alert if expiring in less than 30 days
```

---

## Troubleshooting

| Issue | Solution |
|-------|----------|
| `HandshakeException` | Certificate pin doesn't match. Re-extract and update. |
| `Connection refused` | API server is down or certificate misconfigured. |
| `Certificate pin mismatch` | Certificate rotated on server. Update backup pin first. |
| `OpenSSL not found` | Install: `choco install openssl` (Windows) or `brew install openssl` (Mac) |
| `sha256: command not found` | Update OpenSSL or use online tool at sslshopper.com |

---

## Files to Update

1. ✅ **api_client.dart** - Main certificate pin constants
2. ✅ **build_config.dart** - Environment-specific pins
3. ✅ **android/app/src/main/res/xml/network_security_config.xml** - Android native config
4. ✅ **ios/Runner/Info.plist** - iOS ATS configuration
5. ✅ **pubspec.yaml** - Add crypto dependency

---

## Production Checklist

- [ ] Extract certificate pin from api.tipsytheoryy.com
- [ ] Update PRODUCTION_PIN in api_client.dart
- [ ] Update build_config.dart with correct pins
- [ ] Configure Android network security config
- [ ] Test with 5-10 devices on closed testing track
- [ ] Monitor for certificate pinning errors in logs
- [ ] Set up certificate expiration alerts
- [ ] Document certificate rotation schedule
- [ ] Get sign-off from security team
- [ ] Submit to Play Store with closed testing

**Status:** Ready for Certificate Extraction ✅
