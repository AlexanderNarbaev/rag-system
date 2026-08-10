# Гайд по настройке TLS

Этот гайд охватывает конфигурацию TLS/HTTPS в системе RAG, включая разработку (самоподписанные сертификаты) и продакшен (Let's Encrypt / корпоративный CA).

## Содержание

- [Обзор](#обзор)
- [Архитектура](#архитектура)
- [Настройка для разработки](#настройка-для-разработки)
- [Настройка для продакшена](#настройка-для-продакшена)
- [Ротация сертификатов](#ротация-сертификатов)
- [Решение проблем](#решение-проблем)

## Обзор

Система RAG использует TLS для шифрования всего трафика между клиентами и прокси-сервером. TLS-термирование выполняет nginx или HAProxy, действующий как обратный прокси перед FastAPI-приложением.

### Ключевые свойства безопасности

- **Только TLS 1.2+** — TLS 1.0 и 1.1 отключены
- **Сильные наборы шифров** — AEAD-шифры с Perfect Forward Secrecy
- **Заголовки безопасности** — HSTS, X-Frame-Options, CSP и др.
- **Rate limiting** — Ограничение запросов по IP
- **OCSP stapling** — Эффективная проверка отзыва сертификатов

## Архитектура

```
┌─────────────┐     HTTPS      ┌─────────────┐     HTTP      ┌─────────────┐
│   Клиент    │ ──────────────► │   nginx/    │ ─────────────► │   RAG       │
│ (браузер)   │                 │   HAProxy   │                │   Proxy     │
└─────────────┘                 └─────────────┘                └─────────────┘
                                      │
                                      │ Термирование TLS
                                      │ (сертификаты тут)
                                      ▼
                                ┌─────────────┐
                                │   SSL       │
                                │   серт.     │
                                └─────────────┘
```

## Настройка для разработки

### Самоподписанные сертификаты

Для разработки используйте предоставленный скрипт:

```bash
# Перейти в директорию nginx
cd deploy/nginx

# Сгенерировать сертификаты (по умолчанию: localhost, 365 дней)
./generate-certs.sh

# Или с параметрами
./generate-certs.sh ./ssl 365 mydomain.local
```

Генерируются:
- `ca.crt` / `ca.key` — CA-сертификат и ключ
- `server.crt` / `server.key` — серверный сертификат и ключ
- `dhparam.pem` — параметры Diffie–Hellman

### Запуск через Docker Compose

```bash
# Запустить все сервисы, включая nginx
cd deploy/docker
docker compose -f docker-compose.prod.yml up -d

# Проверить работу TLS
curl -v --cacert ../nginx/ssl/ca.crt https://localhost/v1/health
```

### Доверие самоподписанному сертификату

Чтобы избежать предупреждений браузера, добавьте CA-сертификат в системное хранилище:

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

## Настройка для продакшена

### Вариант 1: Let's Encrypt (рекомендуется для публичных доменов)

Let's Encrypt предоставляет бесплатные автоматизированные TLS-сертификаты.

#### Предварительные требования

- Доменное имя, указывающее на ваш сервер
- Порт 80 доступен из интернета
- Установленный Certbot

#### Установка

```bash
# Установить certbot
sudo apt-get update
sudo apt-get install certbot

# или на macOS
brew install certbot
```

#### Генерация сертификата

```bash
# Остановить nginx временно
docker compose -f docker-compose.prod.yml stop nginx

# Сгенерировать сертификат
sudo certbot certonly --standalone \
  -d your-domain.com \
  -d www.your-domain.com \
  --email admin@your-domain.com \
  --agree-tos \
  --no-eff-email

# Сертификаты хранятся в:
# /etc/letsencrypt/live/your-domain.com/fullchain.pem
# /etc/letsencrypt/live/your-domain.com/privkey.pem
```

#### Конфигурация nginx для Let's Encrypt

Обновите `deploy/nginx/nginx.conf`:

```nginx
server {
    listen 443 ssl http2;
    server_name your-domain.com;

    ssl_certificate /etc/letsencrypt/live/your-domain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/your-domain.com/privkey.pem;

    # ... остальная конфигурация
}
```

#### Автообновление

Certbot автоматически обновляет сертификаты. Добавьте cron-задачу для перезапуска nginx после обновления:

```bash
# Редактировать crontab
crontab -e

# Добавить строку (обновление в 3 утра каждый день)
0 3 * * * certbot renew --quiet && docker compose -f /path/to/docker-compose.prod.yml restart nginx
```

### Вариант 2: Корпоративный CA

Для корпоративных сред используйте CA вашей организации.

#### Генерация CSR

```bash
# Сгенерировать приватный ключ
openssl genrsa -out server.key 2048

# Сгенерировать CSR
openssl req -new -key server.key -out server.csr \
  -subj "/C=RU/ST=Moscow/L=Moscow/O=YourOrg/OU=IT/CN=rag.yourcorp.com"

# Отправить CSR в ваш CA и получить подписанный сертификат
```

#### Установка сертификата

```bash
# Скопировать сертификаты
cp server.crt deploy/nginx/ssl/server.crt
cp server.key deploy/nginx/ssl/server.key
cp ca-chain.crt deploy/nginx/ssl/ca.crt

# Установить права
chmod 400 deploy/nginx/ssl/server.key
chmod 444 deploy/nginx/ssl/server.crt
chmod 444 deploy/nginx/ssl/ca.crt
```

#### Конфигурация nginx

Обновите `deploy/nginx/nginx.conf` для корпоративных сертификатов:

```nginx
ssl_certificate /etc/nginx/ssl/server.crt;
ssl_certificate_key /etc/nginx/ssl/server.key;
ssl_trusted_certificate /etc/nginx/ssl/ca.crt;
```

### Вариант 3: Конфигурация HAProxy

При использовании HAProxy вместо nginx:

#### Подготовка PEM-файла

HAProxy требует сертификат и ключ в одном PEM-файле:

```bash
# Объединить сертификат и ключ
cat server.crt server.key > server.pem
chmod 600 server.pem

# Скопировать в директорию HAProxy
cp server.pem deploy/haproxy/ssl/server.pem
```

#### Запуск с HAProxy

```bash
# Специфичный для HAProxy docker-compose (см. deploy/haproxy/haproxy.cfg)
docker compose -f docker-compose.prod.yml up -d
```

## Ротация сертификатов

### Ручная ротация

#### nginx

```bash
# 1. Сгенерировать новый сертификат
./deploy/nginx/generate-certs.sh ./new-ssl

# 2. Заменить старые сертификаты
cp new-ssl/server.crt deploy/nginx/ssl/server.crt
cp new-ssl/server.key deploy/nginx/ssl/server.key

# 3. Проверить конфигурацию nginx
docker compose -f docker-compose.prod.yml exec nginx nginx -t

# 4. Перезагрузить nginx (без простоя)
docker compose -f docker-compose.prod.yml exec nginx nginx -s reload
```

#### HAProxy

HAProxy поддерживает обновление сертификата без перезапуска:

```bash
# 1. Подготовить новый PEM-файл
cat new-server.crt new-server.key > new-server.pem

# 2. Обновить сертификат через stats-сокет
echo "set ssl cert /etc/haproxy/ssl/server.pem < new-server.pem" | \
  socat stdio /var/run/haproxy.sock

# 3. Подтвердить изменения
echo "commit ssl cert /etc/haproxy/ssl/server.pem" | \
  socat stdio /var/run/haproxy.sock
```

### Автоматическая ротация

#### Автообновление Let's Encrypt

```bash
#!/bin/bash
# /etc/cron.d/certbot-renew

# Обновлять сертификаты в 3 утра каждый день
0 3 * * * root certbot renew --quiet --deploy-hook "docker compose -f /opt/rag-system/deploy/docker/docker-compose.prod.yml restart nginx"
```

#### Скрипт ротации корпоративного CA

```bash
#!/bin/bash
# scripts/rotate-certs.sh

set -euo pipefail

CERT_DIR="/opt/rag-system/deploy/nginx/ssl"
BACKUP_DIR="/opt/rag-system/backups/certs/$(date +%Y%m%d_%H%M%S)"

# Бэкап старых сертификатов
mkdir -p "$BACKUP_DIR"
cp "$CERT_DIR"/*.crt "$BACKUP_DIR/"
cp "$CERT_DIR"/*.key "$BACKUP_DIR/"

# Копировать новые сертификаты
cp /path/to/new/server.crt "$CERT_DIR/"
cp /path/to/new/server.key "$CERT_DIR/"

# Установить права
chmod 400 "$CERT_DIR/server.key"
chmod 444 "$CERT_DIR/server.crt"

# Проверить и перезагрузить nginx
docker compose -f /opt/rag-system/deploy/docker/docker-compose.prod.yml exec nginx nginx -t
docker compose -f /opt/rag-system/deploy/docker/docker-compose.prod.yml exec nginx nginx -s reload

echo "Ротация сертификатов успешно завершена"
echo "Бэкап сохранён в: $BACKUP_DIR"
```

## Health-check TLS

RAG-прокси включает эндпоинт проверки TLS на `/v1/health/tls`:

```bash
# Проверить состояние TLS
curl https://localhost/v1/health/tls

# Ответ:
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

## Решение проблем

### Распространённые проблемы

#### Ошибка верификации сертификата

```bash
# Ошибка: SSL certificate problem: unable to get local issuer certificate
# Решение: указать CA-сертификат
curl --cacert deploy/nginx/ssl/ca.crt https://localhost/v1/health
```

#### Сертификат истёк

```bash
# Проверить срок действия
openssl x509 -in deploy/nginx/ssl/server.crt -noout -dates

# Если истёк, сгенерировать заново
./deploy/nginx/generate-certs.sh
```

#### Слабый cipher suite

```bash
# Проверить наборы шифров
nmap --script ssl-enum-ciphers -p 443 localhost

# Ожидается: только TLS 1.2+ с сильными шифрами
```

#### Ошибка конфигурации nginx

```bash
# Проверить конфигурацию
docker compose -f docker-compose.prod.yml exec nginx nginx -t

# Посмотреть логи
docker compose -f docker-compose.prod.yml logs nginx
```

### Отладка TLS-соединения

```bash
# Подробное TLS-соединение
openssl s_client -connect localhost:443 -servername localhost

# Показать цепочку сертификатов
openssl s_client -connect localhost:443 -showcerts

# Проверить конкретную версию TLS
openssl s_client -connect localhost:443 -tls1_2
openssl s_client -connect localhost:443 -tls1_3
```

## Лучшие практики безопасности

1. **Никогда не коммитьте приватные ключи** — добавьте `*.key` в `.gitignore`
2. **Используйте сильные размеры ключей** — RSA 2048+ или ECDSA 256+
3. **Включайте HSTS** — предотвращает downgrade-атаки
4. **Отключите session tickets** — для Perfect Forward Secrecy
5. **Регулярная ротация** — обновляйте сертификаты до истечения
6. **Мониторьте истечение** — настройте алерты на expiration
7. **Используйте OCSP stapling** — эффективная проверка отзыва
8. **Ограничьте cipher suites** — только AEAD с PFS

## Ссылки

- [Mozilla SSL Configuration Generator](https://ssl-config.mozilla.org/)
- [Документация Let's Encrypt](https://letsencrypt.org/docs/)
- [nginx SSL Termination](https://nginx.org/en/docs/http/configuring_https_servers.html)
- [HAProxy SSL/TLS Configuration](https://www.haproxy.com/blog/haproxy-ssl-termination/)
