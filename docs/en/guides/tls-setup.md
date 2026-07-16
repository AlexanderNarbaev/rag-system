# TLS Setup Guide

This guide covers TLS/HTTPS configuration for the RAG System, including development (self-signed certificates) and production (Let's Encrypt / corporate CA) setups.

## Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Development Setup](#development-setup)
- [Production Setup](#production-setup)
- [Certificate Rotation](#certificate-rotation)
- [Troubleshooting](#troubleshooting)

## Overview

The RAG System uses TLS to encrypt all traffic between clients and the proxy server. TLS termination is handled by either nginx or HAProxy, which acts as a reverse proxy in front of the FastAPI application.

### Key Security Features

- **TLS 1.2+ only** — TLS 1.0 and 1.1 are disabled
- **Strong cipher suites** — AEAD ciphers with Perfect Forward Secrecy
- **Security headers** — HSTS, X-Frame-Options, CSP, etc.
- **Rate limiting** — Per-IP request rate limiting
- **OCSP stapling** — Efficient certificate revocation checking

## Architecture

```
┌─────────────┐     HTTPS      ┌─────────────┐     HTTP      ┌─────────────┐
│   Client    │ ──────────────► │   nginx/    │ ─────────────► │   RAG       │
│   (Browser) │                 │   HAProxy   │                │   Proxy     │
└─────────────┘                 └─────────────┘                └─────────────┘
                                      │
                                      │ TLS termination
                                      │ (certificates stored here)
                                      ▼
                                ┌─────────────┐
                                │   SSL       │
                                │   Certs     │
                                └─────────────┘
```

## Development Setup

### Self-Signed Certificates

For development, use the provided script to generate self-signed certificates:

```bash
# Navigate to nginx directory
cd deploy/nginx

# Generate certificates (default: localhost, 365 days)
./generate-certs.sh

# Or with custom options
./generate-certs.sh ./ssl 365 mydomain.local
```

This generates:
- `ca.crt` / `ca.key` — CA certificate and key
- `server.crt` / `server.key` — Server certificate and key
- `dhparam.pem` — Diffie-Hellman parameters

### Start with Docker Compose

```bash
# Start all services including nginx
cd deploy/docker
docker compose -f docker-compose.prod.yml up -d

# Verify TLS is working
curl -v --cacert ../nginx/ssl/ca.crt https://localhost/v1/health
```

### Trust Self-Signed Certificate

To avoid browser warnings, add the CA certificate to your system trust store:

**macOS:**
```bash
sudo security add-trusted-cert -d -r trustRoot -k /Library/Keychains/System.keychain deploy/nginx/ssl/ca.crt
```

**Linux (Ubuntu/Debian):**
```bash
sudo cp deploy/nginx/ssl/ca.crt /usr/local/share/ca-certificates/rag-system.crt
sudo update-ca-certificates
```

**Windows:**
```powershell
Import-Certificate -FilePath "deploy\nginx\ssl\ca.crt" -CertStoreLocation Cert:\LocalMachine\Root
```

## Production Setup

### Option 1: Let's Encrypt (Recommended for Public Domains)

Let's Encrypt provides free, automated TLS certificates.

#### Prerequisites

- Domain name pointing to your server
- Port 80 accessible from the internet
- Certbot installed

#### Installation

```bash
# Install certbot
sudo apt-get update
sudo apt-get install certbot

# Or on macOS
brew install certbot
```

#### Generate Certificate

```bash
# Stop nginx temporarily
docker compose -f docker-compose.prod.yml stop nginx

# Generate certificate
sudo certbot certonly --standalone \
  -d your-domain.com \
  -d www.your-domain.com \
  --email admin@your-domain.com \
  --agree-tos \
  --no-eff-email

# Certificates are stored in:
# /etc/letsencrypt/live/your-domain.com/fullchain.pem
# /etc/letsencrypt/live/your-domain.com/privkey.pem
```

#### Configure nginx for Let's Encrypt

Update `deploy/nginx/nginx.conf`:

```nginx
server {
    listen 443 ssl http2;
    server_name your-domain.com;

    ssl_certificate /etc/letsencrypt/live/your-domain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/your-domain.com/privkey.pem;

    # ... rest of configuration
}
```

#### Auto-Renewal

Certbot automatically renews certificates. Add a cron job to restart nginx after renewal:

```bash
# Edit crontab
crontab -e

# Add this line (renew at 3am daily)
0 3 * * * certbot renew --quiet && docker compose -f /path/to/docker-compose.prod.yml restart nginx
```

### Option 2: Corporate CA

For enterprise environments, use your organization's Certificate Authority.

#### Generate CSR

```bash
# Generate private key
openssl genrsa -out server.key 2048

# Generate CSR
openssl req -new -key server.key -out server.csr \
  -subj "/C=RU/ST=Moscow/L=Moscow/O=YourOrg/OU=IT/CN=rag.yourcorp.com"

# Submit CSR to your CA and receive signed certificate
```

#### Install Certificate

```bash
# Copy certificates
cp server.crt deploy/nginx/ssl/server.crt
cp server.key deploy/nginx/ssl/server.key
cp ca-chain.crt deploy/nginx/ssl/ca.crt

# Set permissions
chmod 400 deploy/nginx/ssl/server.key
chmod 444 deploy/nginx/ssl/server.crt
chmod 444 deploy/nginx/ssl/ca.crt
```

#### Configure nginx

Update `deploy/nginx/nginx.conf` to use corporate certificates:

```nginx
ssl_certificate /etc/nginx/ssl/server.crt;
ssl_certificate_key /etc/nginx/ssl/server.key;
ssl_trusted_certificate /etc/nginx/ssl/ca.crt;
```

### Option 3: HAProxy Configuration

If using HAProxy instead of nginx:

#### Prepare PEM File

HAProxy requires certificate and key in a single PEM file:

```bash
# Combine certificate and key
cat server.crt server.key > server.pem
chmod 600 server.pem

# Copy to HAProxy directory
cp server.pem deploy/haproxy/ssl/server.pem
```

#### Start with HAProxy

```bash
# Use HAProxy-specific docker-compose (see deploy/haproxy/haproxy.cfg)
docker compose -f docker-compose.prod.yml up -d
```

## Certificate Rotation

### Manual Rotation

#### nginx

```bash
# 1. Generate new certificate
./deploy/nginx/generate-certs.sh ./new-ssl

# 2. Replace old certificates
cp new-ssl/server.crt deploy/nginx/ssl/server.crt
cp new-ssl/server.key deploy/nginx/ssl/server.key

# 3. Test nginx configuration
docker compose -f docker-compose.prod.yml exec nginx nginx -t

# 4. Reload nginx (zero-downtime)
docker compose -f docker-compose.prod.yml exec nginx nginx -s reload
```

#### HAProxy

HAProxy supports runtime certificate updates without restart:

```bash
# 1. Prepare new PEM file
cat new-server.crt new-server.key > new-server.pem

# 2. Update certificate via stats socket
echo "set ssl cert /etc/haproxy/ssl/server.pem < new-server.pem" | \
  socat stdio /var/run/haproxy.sock

# 3. Commit changes
echo "commit ssl cert /etc/haproxy/ssl/server.pem" | \
  socat stdio /var/run/haproxy.sock
```

### Automated Rotation

#### Let's Encrypt Auto-Renewal

```bash
#!/bin/bash
# /etc/cron.d/certbot-renew

# Renew certificates at 3am daily
0 3 * * * root certbot renew --quiet --deploy-hook "docker compose -f /opt/rag-system/deploy/docker/docker-compose.prod.yml restart nginx"
```

#### Corporate CA Rotation Script

```bash
#!/bin/bash
# scripts/rotate-certs.sh

set -euo pipefail

CERT_DIR="/opt/rag-system/deploy/nginx/ssl"
BACKUP_DIR="/opt/rag-system/backups/certs/$(date +%Y%m%d_%H%M%S)"

# Backup old certificates
mkdir -p "$BACKUP_DIR"
cp "$CERT_DIR"/*.crt "$BACKUP_DIR/"
cp "$CERT_DIR"/*.key "$BACKUP_DIR/"

# Copy new certificates (provided by CA)
cp /path/to/new/server.crt "$CERT_DIR/"
cp /path/to/new/server.key "$CERT_DIR/"

# Set permissions
chmod 400 "$CERT_DIR/server.key"
chmod 444 "$CERT_DIR/server.crt"

# Test and reload nginx
docker compose -f /opt/rag-system/deploy/docker/docker-compose.prod.yml exec nginx nginx -t
docker compose -f /opt/rag-system/deploy/docker/docker-compose.prod.yml exec nginx nginx -s reload

echo "Certificate rotation completed successfully"
echo "Backup saved to: $BACKUP_DIR"
```

## TLS Health Check

The RAG proxy includes a TLS health check endpoint at `/v1/health/tls`:

```bash
# Check TLS status
curl https://localhost/v1/health/tls

# Response:
{
  "status": "ok",
  "tls": {
    "enabled": true,
    "version": "TLSv1.3",
    "cipher": "TLS_AES_256_GCM_SHA384",
    "certificate_valid": true,
    "days_until_expiry": 89
  }
}
```

## Troubleshooting

### Common Issues

#### Certificate Verification Failed

```bash
# Error: SSL certificate problem: unable to get local issuer certificate
# Solution: Provide CA certificate
curl --cacert deploy/nginx/ssl/ca.crt https://localhost/v1/health
```

#### Certificate Expired

```bash
# Check certificate expiration
openssl x509 -in deploy/nginx/ssl/server.crt -noout -dates

# If expired, regenerate or obtain new certificate
./deploy/nginx/generate-certs.sh
```

#### Weak Cipher Suite

```bash
# Test cipher suites
nmap --script ssl-enum-ciphers -p 443 localhost

# Expected: Only TLS 1.2+ with strong ciphers
```

#### nginx Configuration Error

```bash
# Test configuration
docker compose -f docker-compose.prod.yml exec nginx nginx -t

# Check logs
docker compose -f docker-compose.prod.yml logs nginx
```

### Debug TLS Connection

```bash
# Verbose TLS connection
openssl s_client -connect localhost:443 -servername localhost

# Show certificate chain
openssl s_client -connect localhost:443 -showcerts

# Test specific TLS version
openssl s_client -connect localhost:443 -tls1_2
openssl s_client -connect localhost:443 -tls1_3
```

## Security Best Practices

1. **Never commit private keys** — Add `*.key` to `.gitignore`
2. **Use strong key sizes** — RSA 2048+ or ECDSA 256+
3. **Enable HSTS** — Prevents downgrade attacks
4. **Disable session tickets** — For Perfect Forward Secrecy
5. **Regular rotation** — Rotate certificates before expiration
6. **Monitor expiration** — Set up alerts for certificate expiry
7. **Use OCSP stapling** — Efficient revocation checking
8. **Restrict cipher suites** — Only AEAD ciphers with PFS

## References

- [Mozilla SSL Configuration Generator](https://ssl-config.mozilla.org/)
- [Let's Encrypt Documentation](https://letsencrypt.org/docs/)
- [nginx SSL Termination](https://nginx.org/en/docs/http/configuring_https_servers.html)
- [HAProxy SSL/TLS Configuration](https://www.haproxy.com/blog/haproxy-ssl-termination/)
