# Заготовки для развёртывания

В этой директории — шаблоны конфигурации для публикации сервиса в интернет
под собственным доменом.

## Файлы

| Файл | Назначение |
|------|------------|
| `nginx.conf.example` | Reverse proxy с HTTPS через Let's Encrypt |
| `retake.service.example` | systemd-сервис для автозапуска (Linux) |

## Быстрый порядок действий

1. **Установить домен** на ПК → раздел README.md → «Настройка домена и публикация в интернет».
2. **Скопировать** `nginx.conf.example` → `/etc/nginx/sites-available/retake`.
3. **Заменить** `YOUR_DOMAIN` на свой домен (`sed -i 's/YOUR_DOMAIN/retake.example.com/g'`).
4. **Получить TLS-сертификат**: `sudo certbot --nginx -d retake.example.com`.
5. **Скопировать** `retake.service.example` → `/etc/systemd/system/retake.service`.
6. **Заменить** `YOUR_USER` и `PATH_TO_PROJECT` на реальные значения.
7. **Запустить**:
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable --now retake
   sudo systemctl reload nginx
   ```

Подробные инструкции — в основном `README.md` корня проекта.
