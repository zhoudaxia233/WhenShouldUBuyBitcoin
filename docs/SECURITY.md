# Security Guide

Production security checklist and best practices for DCA Service authentication.

## Environment Variables

### Required
```bash
# Session secret - MUST be cryptographically strong
# Generate with: python -c "import secrets; print(secrets.token_urlsafe(32))"
SESSION_SECRET=your-random-32-byte-secret-here

# Database
DATABASE_URL=sqlite:///./dca.db

# Other existing configs
BINANCE_CRED_ENC_KEY=your-encryption-key
```

### Optional Production Overrides
```bash
# Enable HTTPS-only cookies (default: true)
SESSION_COOKIE_HTTPS_ONLY=true

# SameSite cookie policy (default: lax)
SESSION_COOKIE_SAMESITE=lax

# Session timeout in seconds (default: 86400 = 24 hours)
SESSION_MAX_AGE=86400
```

## Production Deployment Checklist

### 1. Reverse Proxy (nginx/Traefik)
- ✅ Run FastAPI on localhost only (not exposed publicly)
- ✅ Configure nginx/Traefik to handle HTTPS
- ✅ Set proper SSL/TLS certificates (Let's Enc rypt recommended)
- ✅ Forward requests to localhost:8000

**Example nginx config:**
```nginx
server {
    listen 443 ssl;
    server_name your-domain.com;
    
    ssl_certificate /path/to/cert.pem;
    ssl_certificate_key /path/to/key.pem;
    
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

### 2. Rate Limiting
Protect `/api/auth/login` from brute-force attacks:

**nginx rate limiting:**
```nginx
limit_req_zone $binary_remote_addr zone=login_limit:10m rate=5r/m;

location /api/auth/login {
    limit_req zone=login_limit burst=3 nodelay;
    proxy_pass http://127.0.0.1:8000;
}
```

### 3. Session Security
- ✅ Generate strong `SESSION_SECRET` (≥32 bytes random)
- ✅ Never commit `SESSION_SECRET` to git
- ✅ Set `SESSION_COOKIE_HTTPS_ONLY=true` in production
- ✅ Use `SameSite=lax` or `strict` for CSRF protection

### 4. Password Security
- ✅ Minimum password length enforced (8+ characters)
- ✅ Bcrypt hashing with automatic salting
- ✅ Never log or display passwords
- ✅ No default admin users with fixed passwords

### 5. Admin User Creation
Do NOT auto-create admin users in production. Use the script:

```bash
poetry run python scripts/create_admin.py
```

### 6. Logging & Monitoring
Configure logging for security events:
- Failed login attempts
- CSRF validation failures
- Session anomalies
- Rate limit violations

**Example: Add to application logs**
```python
# dca_service logs failed logins automatically
# Check logs/dca_service.log for:
# "Failed login attempt for email: user@example.com"
# "CSRF validation failed"
```

### 7. Database Security
- ✅ Use parameterized queries (SQLModel does this)
- ✅ Never expose database credentials in logs
- ✅ Regularly backup database
- ✅ Store backups securely (encrypted)

### 8. HTTPS Only
- ✅ Always use HTTPS in production
- ✅ Redirect HTTP → HTTPS at nginx/Traefik
- ✅ Set `SESSION_COOKIE_HTTPS_ONLY=true`

### 9. Open-Source Considerations
Since your code is open-source:
- ✅ Security relies on architecture, not obscurity
- ✅ All secrets come from environment variables
- ✅ No hardcoded keys in source code
- ✅ Document security assumptions clearly
- ✅ Use industry-standard libraries (passlib, bcrypt)

### 10. Regular Updates
- ✅ Keep dependencies up to date
- ✅ Monitor security advisories for fastapi, passlib, bcrypt
- ✅ Run `poetry update` regularly
- ✅ Test auth system after updates

## Security Best Practices

### Password Requirements
Current requirements (enforced in `create_admin.py`):
- Minimum 8 characters
- Stored as bcrypt hash (never plaintext)

**Recommended enhancements:**
- Require mix of uppercase, lowercase, numbers
- Check against common password lists
- Implement password expiration policy

### Session Management
- Sessions expire after 24 hours (configurable)
- Sessions cleared on logout
- Stale sessions automatically invalidated

### CSRF Protection
- All state-changing forms include CSRF tokens
- Tokens are cryptographically random (32 bytes)
- Tokens validated using constant-time comparison

## Disaster Recovery

### Lost Admin Password
If admin loses password, create a new admin:
```bash
poetry run python scripts/create_admin.py
```

Then disable the old admin in the database:
```sql
UPDATE users SET is_active = false WHERE email = 'old@admin.com';
```

### Compromised SESSION_SECRET
1. Generate new secret:
  ```bash
   python -c "import secrets; print(secrets.token_urlsafe(32))"
   ```
2. Update `SESSION_SECRET` environment variable
3. Restart application
4. All existing sessions will be invalidated
5. Users must log in again

## Security Audit Checklist

Before going to production:
- [ ] `SESSION_SECRET` is strong and random
- [ ] HTTPS enabled and enforced
- [ ] Rate limiting configured on `/api/auth/login`
- [ ] No default/test credentials exist
- [ ] Logs configured for security events
- [ ] nginx/Traefik reverse proxy configured
- [ ] Database backups automated
- [ ] All dependencies up to date
- [ ] Environment variables documented
- [ ] Session timeout appropriate for use case

## Reporting Security Issues

If you discover a security vulnerability:
1. Do NOT open a public GitHub issue
2. Email security concerns privately
3. Include reproduction steps
4. Allow reasonable time for patching before disclosure
