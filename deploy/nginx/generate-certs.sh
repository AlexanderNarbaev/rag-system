#!/bin/bash
# deploy/nginx/generate-certs.sh
# Generate self-signed TLS certificates for development
# WARNING: For production, use Let's Encrypt or corporate CA certificates

set -euo pipefail

# ── Configuration ──────────────────────────────────────────────────────────────
CERT_DIR="${1:-./ssl}"
DAYS="${2:-365}"
DOMAIN="${3:-localhost}"
COUNTRY="${4:-RU}"
STATE="${5:-Moscow}"
LOCALITY="${6:-Moscow}"
ORG="${7:-RAG-System}"
OU="${8:-Development}"

# ── Colors for output ─────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# ── Functions ─────────────────────────────────────────────────────────────────
log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# ── Check dependencies ────────────────────────────────────────────────────────
check_dependencies() {
    if ! command -v openssl &> /dev/null; then
        log_error "OpenSSL is not installed. Please install it first."
        exit 1
    fi
    log_info "OpenSSL version: $(openssl version)"
}

# ── Create certificate directory ──────────────────────────────────────────────
create_cert_dir() {
    if [ ! -d "$CERT_DIR" ]; then
        mkdir -p "$CERT_DIR"
        log_info "Created certificate directory: $CERT_DIR"
    fi
    chmod 700 "$CERT_DIR"
}

# ── Generate DH parameters ────────────────────────────────────────────────────
generate_dhparam() {
    local dhparam_file="$CERT_DIR/dhparam.pem"
    
    if [ -f "$dhparam_file" ]; then
        log_warn "DH parameters file already exists: $dhparam_file"
        log_warn "To regenerate, delete the file first."
        return
    fi
    
    log_info "Generating DH parameters (2048-bit)... This may take a while."
    openssl dhparam -out "$dhparam_file" 2048
    log_info "DH parameters generated: $dhparam_file"
}

# ── Generate CA certificate ───────────────────────────────────────────────────
generate_ca() {
    local ca_key="$CERT_DIR/ca.key"
    local ca_cert="$CERT_DIR/ca.crt"
    
    if [ -f "$ca_key" ] && [ -f "$ca_cert" ]; then
        log_warn "CA certificate already exists. Skipping generation."
        return
    fi
    
    log_info "Generating CA private key..."
    openssl genrsa -out "$ca_key" 4096
    chmod 400 "$ca_key"
    
    log_info "Generating CA certificate..."
    openssl req -new -x509 -days "$DAYS" -key "$ca_key" -out "$ca_cert" \
        -subj "/C=$COUNTRY/ST=$STATE/L=$LOCALITY/O=$ORG/OU=$OU/CN=RAG-System-CA"
    
    log_info "CA certificate generated: $ca_cert"
}

# ── Generate server certificate ───────────────────────────────────────────────
generate_server_cert() {
    local ca_key="$CERT_DIR/ca.key"
    local ca_cert="$CERT_DIR/ca.crt"
    local server_key="$CERT_DIR/server.key"
    local server_csr="$CERT_DIR/server.csr"
    local server_cert="$CERT_DIR/server.crt"
    local server_ext="$CERT_DIR/server.ext"
    
    if [ -f "$server_key" ] && [ -f "$server_cert" ]; then
        log_warn "Server certificate already exists. Skipping generation."
        return
    fi
    
    # Generate server private key
    log_info "Generating server private key..."
    openssl genrsa -out "$server_key" 2048
    chmod 400 "$server_key"
    
    # Create certificate extensions file for SAN
    cat > "$server_ext" <<EOF
authorityKeyIdentifier=keyid,issuer
basicConstraints=CA:FALSE
keyUsage=digitalSignature,keyEncipherment
extendedKeyUsage=serverAuth
subjectAltName=@alt_names

[alt_names]
DNS.1 = $DOMAIN
DNS.2 = localhost
DNS.3 = rag-proxy
DNS.4 = *.local
IP.1 = 127.0.0.1
IP.2 = ::1
EOF
    
    # Generate CSR
    log_info "Generating Certificate Signing Request (CSR)..."
    openssl req -new -key "$server_key" -out "$server_csr" \
        -subj "/C=$COUNTRY/ST=$STATE/L=$LOCALITY/O=$ORG/OU=$OU/CN=$DOMAIN"
    
    # Sign with CA
    log_info "Signing server certificate with CA..."
    openssl x509 -req -in "$server_csr" -CA "$ca_cert" -CAkey "$ca_key" \
        -CAcreateserial -out "$server_cert" -days "$DAYS" \
        -extfile "$server_ext"
    
    # Clean up temporary files
    rm -f "$server_csr" "$server_ext"
    
    log_info "Server certificate generated: $server_cert"
}

# ── Generate client certificate (optional, for mTLS) ──────────────────────────
generate_client_cert() {
    local ca_key="$CERT_DIR/ca.key"
    local ca_cert="$CERT_DIR/ca.crt"
    local client_key="$CERT_DIR/client.key"
    local client_csr="$CERT_DIR/client.csr"
    local client_cert="$CERT_DIR/client.crt"
    local client_ext="$CERT_DIR/client.ext"
    
    if [ -f "$client_key" ] && [ -f "$client_cert" ]; then
        log_warn "Client certificate already exists. Skipping generation."
        return
    fi
    
    log_info "Generating client private key..."
    openssl genrsa -out "$client_key" 2048
    chmod 400 "$client_key"
    
    # Create certificate extensions file
    cat > "$client_ext" <<EOF
authorityKeyIdentifier=keyid,issuer
basicConstraints=CA:FALSE
keyUsage=digitalSignature,keyEncipherment
extendedKeyUsage=clientAuth
EOF
    
    # Generate CSR
    log_info "Generating client CSR..."
    openssl req -new -key "$client_key" -out "$client_csr" \
        -subj "/C=$COUNTRY/ST=$STATE/L=$LOCALITY/O=$ORG/OU=$OU/CN=client"
    
    # Sign with CA
    log_info "Signing client certificate with CA..."
    openssl x509 -req -in "$client_csr" -CA "$ca_cert" -CAkey "$ca_key" \
        -CAcreateserial -out "$client_cert" -days "$DAYS" \
        -extfile "$client_ext"
    
    # Clean up temporary files
    rm -f "$client_csr" "$client_ext"
    
    log_info "Client certificate generated: $client_cert"
}

# ── Generate Diffie-Hellman parameters ────────────────────────────────────────
generate_dhparam_if_needed() {
    local dhparam_file="$CERT_DIR/dhparam.pem"
    
    if [ ! -f "$dhparam_file" ]; then
        generate_dhparam
    else
        log_info "DH parameters file already exists."
    fi
}

# ── Verify certificates ───────────────────────────────────────────────────────
verify_certificates() {
    local ca_cert="$CERT_DIR/ca.crt"
    local server_cert="$CERT_DIR/server.crt"
    
    log_info "Verifying certificates..."
    
    # Verify CA certificate
    if [ -f "$ca_cert" ]; then
        log_info "CA Certificate:"
        openssl x509 -in "$ca_cert" -noout -subject -issuer -dates
    fi
    
    # Verify server certificate
    if [ -f "$server_cert" ]; then
        log_info "Server Certificate:"
        openssl x509 -in "$server_cert" -noout -subject -issuer -dates
        
        # Verify against CA
        if openssl verify -CAfile "$ca_cert" "$server_cert" > /dev/null 2>&1; then
            log_info "Server certificate is valid and signed by CA."
        else
            log_error "Server certificate verification failed!"
        fi
    fi
}

# ── Print summary ─────────────────────────────────────────────────────────────
print_summary() {
    echo ""
    echo "=========================================="
    echo "  TLS Certificate Generation Complete"
    echo "=========================================="
    echo ""
    echo "Generated files in: $CERT_DIR"
    echo ""
    echo "  CA Certificate:     $CERT_DIR/ca.crt"
    echo "  CA Private Key:     $CERT_DIR/ca.key"
    echo "  Server Certificate: $CERT_DIR/server.crt"
    echo "  Server Private Key: $CERT_DIR/server.key"
    echo "  DH Parameters:      $CERT_DIR/dhparam.pem"
    echo ""
    echo "For mTLS (mutual TLS):"
    echo "  Client Certificate: $CERT_DIR/client.crt"
    echo "  Client Private Key: $CERT_DIR/client.key"
    echo ""
    echo "Next steps:"
    echo "  1. Copy certificates to nginx ssl directory:"
    echo "     cp $CERT_DIR/* /etc/nginx/ssl/"
    echo ""
    echo "  2. Restart nginx:"
    echo "     docker compose restart nginx"
    echo ""
    echo "  3. Test TLS connection:"
    echo "     curl -v --cacert $CERT_DIR/ca.crt https://localhost/v1/health"
    echo ""
    echo "WARNING: These are self-signed certificates for development only!"
    echo "         For production, use Let's Encrypt or corporate CA."
    echo "=========================================="
}

# ── Main ──────────────────────────────────────────────────────────────────────
main() {
    echo "=========================================="
    echo "  RAG System TLS Certificate Generator"
    echo "=========================================="
    echo ""
    
    check_dependencies
    create_cert_dir
    generate_ca
    generate_server_cert
    generate_client_cert
    generate_dhparam_if_needed
    verify_certificates
    print_summary
}

# Run main function
main "$@"
