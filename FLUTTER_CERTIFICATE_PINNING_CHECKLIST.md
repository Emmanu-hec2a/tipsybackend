# Flutter Certificate Pinning - Implementation Checklist

**Status:** Production-Ready for Play Store Closed Testing  
**Date:** 2026-08-24  
**Version:** 1.0  

---

## 📋 Pre-Implementation (Team Review)

- [ ] Security team reviews implementation plan
- [ ] Backend team confirms certificate availability
- [ ] DevOps team confirms certificate rotation schedule
- [ ] QA team prepares test cases for closed testing

---

## 🔐 Step 1: Extract Production Certificate

### 1.1 Get Certificate from API Server

- [ ] Run: `openssl s_client -connect api.tipsytheoryy.com:443 -showcerts`
- [ ] Save output to file: `api_cert.pem`
- [ ] Verify certificate subject: `CN=api.tipsytheoryy.com`

**Reference:** See `CERTIFICATE_PIN_EXTRACTION_GUIDE.md`

### 1.2 Generate SHA256 Public Key Hash

```bash
openssl x509 -in api_cert.pem -pubkey -noout | \
  openssl pkey -pubin -outform DER | openssl dgst -sha256 -binary | openssl enc -base64
```

- [ ] Note down the hash: `sha256/ABC123DEF456...`
- [ ] Verify it matches expected format (base64, ~44 chars)
- [ ] Store in secure location (password manager / 1Password)

### 1.3 Extract Backup Certificate (Optional but Recommended)

- [ ] If new certificate already deployed: extract its pin
- [ ] Generate backup pin: `sha256/DEF456GHI789...`
- [ ] This enables smooth certificate rotation

**Result:** 
- Production PIN: ___________________
- Backup PIN: ___________________

---

## 📱 Step 2: Add Dependencies to Flutter

- [ ] Open `pubspec.yaml` in your Flutter project
- [ ] Add dependencies (see `pubspec.yaml.snippet`):
  - [ ] `dio: ^5.3.0` - HTTP client
  - [ ] `crypto: ^3.0.0` - SHA256 support
  - [ ] `flutter_secure_storage: ^9.0.0` - Token storage

```bash
flutter pub get
```

- [ ] Verify dependencies are installed
- [ ] No version conflicts reported

---

## 💻 Step 3: Implement Certificate Pinning Code

### 3.1 Copy Core Files

- [ ] Copy `api_client.dart` → `lib/services/api_client.dart`
- [ ] Copy `auth_service.dart` → `lib/services/auth_service.dart`
- [ ] Copy `build_config.dart` → `lib/config/build_config.dart`

### 3.2 Update Certificate Pins

**In api_client.dart:**

```dart
static const String PRODUCTION_PIN = 'sha256/ABC123DEF456...';  // Your pin here
static const String PRODUCTION_PIN_BACKUP = 'sha256/DEF456...';  // Your backup pin
```

- [ ] Replace `PRODUCTION_PIN` with extracted pin
- [ ] Replace `PRODUCTION_PIN_BACKUP` with backup pin (or use primary if none)

**In build_config.dart:**

```dart
case 'production':
  return {
    'host': 'api.tipsytheoryy.com',
    'pin': 'sha256/ABC123...',      // Your pin
    'backup_pin': 'sha256/DEF456...', // Your backup pin
  };
```

- [ ] Update production pins in build_config.dart
- [ ] Update staging pins if using staging API
- [ ] Verify all environments configured

### 3.3 Integrate with Existing Auth

- [ ] Replace existing HTTP client with ApiClient
- [ ] Update login flow to use AuthService
- [ ] Remove old HTTP client implementation
- [ ] Verify no duplicate HTTP client code

Example:
```dart
// OLD: 
// final response = await http.post(url, body: data);

// NEW:
final authService = AuthService();
final loginResponse = await authService.login(username: user, password: pass);
```

- [ ] Test API calls still work correctly
- [ ] JWT tokens stored securely
- [ ] Auth flow uninterrupted

---

## 🔧 Step 4: Platform-Specific Configuration

### 4.1 Android Configuration

**android/app/src/main/res/xml/network_security_config.xml:**

```xml
<?xml version="1.0" encoding="utf-8"?>
<network-security-config>
    <domain-config cleartextTrafficPermitted="false">
        <domain includeSubdomains="true">api.tipsytheoryy.com</domain>
        <pin-set expiration="2026-12-31">
            <pin digest="SHA-256">sha256/YOUR_PIN</pin>
            <pin digest="SHA-256">sha256/YOUR_BACKUP_PIN</pin>
        </pin-set>
    </domain-config>
</network-security-config>
```

- [ ] Create `network_security_config.xml` file
- [ ] Add both production and backup pins
- [ ] Set expiration date to certificate renewal date
- [ ] Verify no XML syntax errors

**android/app/src/main/AndroidManifest.xml:**

```xml
<application
    android:networkSecurityConfig="@xml/network_security_config"
    ...>
```

- [ ] Add `android:networkSecurityConfig` attribute
- [ ] Point to `network_security_config.xml`
- [ ] Test app compiles without errors

### 4.2 iOS Configuration

**ios/Runner/Info.plist:**

```xml
<key>NSAppTransportSecurity</key>
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

- [ ] Update ATS configuration in Info.plist
- [ ] Require TLS 1.2 or higher
- [ ] Verify no cleartext traffic allowed

---

## ✅ Step 5: Testing

### 5.1 Unit Tests

**test/services/api_client_test.dart:**

```dart
import 'package:flutter_test/flutter_test.dart';

void main() {
  group('Certificate Pinning', () {
    test('Valid certificate should connect', () async {
      final apiClient = ApiClient();
      final response = await apiClient.get('/api/v1/health/');
      expect(response.statusCode, 200);
    });
  });
}
```

- [ ] Create test file for ApiClient
- [ ] Test successful connection to production API
- [ ] Run: `flutter test test/services/api_client_test.dart`
- [ ] Verify all tests pass

### 5.2 Manual Testing (Local)

```bash
# Build debug version
flutter run --dart-define=ENVIRONMENT=production

# In app:
# 1. Login with test credentials
# 2. Verify JWT token received
# 3. Make API call to verify pinning works
# 4. Check logs for "✅ Certificate pin verified"
```

- [ ] Login successful
- [ ] API calls work correctly
- [ ] Certificate pinning logs show successful verification
- [ ] No SSL/certificate errors

### 5.3 Closed Testing (Real Devices)

- [ ] Build closed testing APK: 
  ```bash
  flutter build apk --dart-define=ENVIRONMENT=closed_testing --split-per-abi
  ```

- [ ] Upload to Play Store internal testing track

- [ ] Test on 5-10 real Android devices:
  - [ ] Device 1: _______ (Phone)
  - [ ] Device 2: _______ (Phone)
  - [ ] Device 3: _______ (Tablet)
  - [ ] Device 4: _______ (Lower Android version)
  - [ ] Device 5: _______ (Higher Android version)

- [ ] For each device:
  - [ ] App installs successfully
  - [ ] Login works
  - [ ] API calls succeed
  - [ ] No SSL/pinning errors in logs
  - [ ] No crashes or exceptions

- [ ] Test Certificate Pinning Explicitly:
  ```dart
  final authService = AuthService();
  await authService.testRateLimiting(orderId: 109, requestCount: 35);
  ```
  - [ ] Verify rate limiting works (30 success, then 429)
  - [ ] No certificate pinning errors

- [ ] Monitor Firebase Crashlytics/Sentry:
  - [ ] No increase in crash rate
  - [ ] No SSL exceptions
  - [ ] No HandshakeException errors

---

## 📊 Step 6: Monitoring & Alerts

### 6.1 Backend Logging

**Add to Django backend (urbanfoods/api_v1_security_views.py):**

```python
class CertificatePinIncidentView(APIView):
    permission_classes = []
    
    def post(self, request):
        incident = {
            'timestamp': datetime.now(),
            'app_version': request.data.get('app_version'),
            'device': request.data.get('device'),
            'error': request.data.get('error'),
        }
        logger.critical(f"Cert pin incident: {incident}")
        return Response({'status': 'logged'})
```

- [ ] Add certificate pin incident logging endpoint
- [ ] Configure to log all pinning failures
- [ ] Set up alert for any pinning errors

### 6.2 Monitoring Dashboard

- [ ] Datadog / New Relic dashboard showing:
  - [ ] Certificate pinning failures over time
  - [ ] SSL handshake errors
  - [ ] App crash rate
  - [ ] API error rate

- [ ] Set up alerts:
  - [ ] Alert if any SSL/certificate errors detected
  - [ ] Alert if crash rate increases > 5%
  - [ ] Alert if certificate expiring in < 30 days

---

## 🚀 Step 7: Production Deployment

### 7.1 Build Production Bundle

```bash
flutter build appbundle --dart-define=ENVIRONMENT=production
```

- [ ] Build succeeds without errors
- [ ] Bundle size reasonable (< 100MB)
- [ ] All production pins configured

### 7.2 Play Store Submission

- [ ] Increment version number in pubspec.yaml
- [ ] Update changelog with certificate pinning security fix
- [ ] Add build to Play Console
- [ ] Select closed testing track for initial release
- [ ] Add description: "Certificate pinning for enhanced security"

### 7.3 Closed Testing Track (2 weeks)

- [ ] Deploy to closed testing track
- [ ] Collect feedback from 50-100 testers
- [ ] Monitor for any SSL/pinning issues
- [ ] Monitor crash rate (target: < 1%)

Closed Testing Checklist:
- [ ] No SSL/certificate errors reported
- [ ] No crashes related to pinning
- [ ] Users can login and use app normally
- [ ] Rate limiting works correctly
- [ ] Feedback positive

### 7.4 Production Release

After successful closed testing:

- [ ] Promote to beta track (1 week)
- [ ] Monitor for issues
- [ ] Promote to production (full rollout)

- [ ] Release to production
- [ ] Monitor metrics for 24 hours
- [ ] Be ready to rollback if issues occur

---

## 🔄 Step 8: Certificate Rotation

### 8.1 Schedule (Every 60 Days)

**Day 0-30:** Current certificate active
- [ ] Cert: ABC123...
- [ ] PIN: sha256/ABC123...
- [ ] Backup: DEF456...

**Day 30:** Issue new certificate, configure as backup
- [ ] New cert issued by certificate authority
- [ ] Configure as backup in all systems
- [ ] PRODUCTION_PIN_BACKUP = sha256/DEF456...

**Day 45:** Push app update with new pin
- [ ] Release new app version with new pin as primary
- [ ] PRODUCTION_PIN = sha256/DEF456...

**Day 60:** Remove old certificate
- [ ] Remove old cert from server
- [ ] PRODUCTION_PIN_BACKUP can now be new cert

### 8.2 Rotation Checklist

- [ ] New certificate obtained from CA
- [ ] Certificate validity verified (minimum 60 days)
- [ ] Backup pin configured (15 days before rotation)
- [ ] App update released with new pin
- [ ] Closed testing verification complete
- [ ] Production rollout successful
- [ ] Old certificate removed from server
- [ ] Monitoring shows no errors during rotation

---

## 📝 Documentation

- [ ] README updated with certificate pinning info
- [ ] API documentation notes pinning requirement
- [ ] Security policy updated
- [ ] Certificate rotation schedule documented
- [ ] Team trained on pinning implementation

---

## ✨ Final Verification

- [ ] Production certificate pin verified
- [ ] Build succeeds for all environments
- [ ] Tests pass on local development
- [ ] Closed testing successful (2+ weeks)
- [ ] No crashes or SSL errors in production
- [ ] Monitoring alerts configured
- [ ] Certificate rotation schedule documented
- [ ] Team trained and ready

---

## 🎯 Success Criteria

✅ **All tests passing**  
✅ **No SSL/certificate errors in production**  
✅ **Closed testing successful with 5+ devices**  
✅ **Rate limiting working (30/hour limit)**  
✅ **Zero crashes related to certificate pinning**  
✅ **Monitoring alerts configured**  
✅ **Team understands certificate rotation process**  

---

## 📞 Support & Escalation

| Issue | Escalation |
|-------|-----------|
| Certificate pin mismatch | Contact DevOps / Backend team |
| SSL errors in production | Page security team - possible incident |
| Crash spike after release | Rollback to previous version immediately |
| Certificate expiration | Backend team to renew certificate |

---

**Checklist Status:** Ready to Execute ✅  
**Implementation Date:** _______________  
**Completion Date:** _______________  
**Sign-off:** _______________  
