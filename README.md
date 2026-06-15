# Спринт 9: BionicPRO

## Задание 1.1
Для устранения уязвимостей и повышения безопасности предлагается следующая архитектура:
1. Внедрение промежуточного бэкенд-сервиса `bionicpro-auth`
- Выступает в роли доверенного посредника между фронтендом и `Keycloak`.
- Реализует PKCE-поток (замена Code Grant) и хранит `access_token` и `refresh_token` на серверной стороне.
- Фронтенд получает только HTTP-only, Secure-сессионную cookie, которая привязана к сессии на сервере.
- Сервис автоматически обновляет `access_token` через `refresh_token`, поддерживает ротацию сессий (против session fixation).
2. Keycloak
- Настроен на использование PKCE для публичного клиента (`reports-frontend`).
- Подключён к LDAP (OpenLDAP) для получения пользователей из внешнего представительства.
- Включена MFA (OTP) для всех пользователей.
- Добавлен Identity Provider «Яндекс ID» через Identity Brokering с запросом согласия (consent).
3. LDAP-сервер
- Развёрнут OpenLDAP с конфигурацией из `ldap/config.ldif`.
- Keycloak синхронизирует пользователей и роли (`user`, `prothetic_user`).
4. Яндекс ID
- Пользователи могут войти через Яндекс. После аутентификации Keycloak запрашивает разрешение на использование данных (консент) и сохраняет профиль.
5. База данных сессий (Redis)
- Используется для хранения сессий и токенов в распределённой среде (можно заменить на in-memory, но для production рекомендуется Redis).
### Диаграмма архитектуры (C4)
![Целевая архитектура безопасности BionicPRO](diagrams/task1_1-architecture.png)

## Задание 1.5: Экспорт realm
- `docker exec architecture-bionicpro-keycloak-1 /opt/keycloak/bin/kc.sh export --realm reports-realm --file /tmp/keycloak-results-export.json --users realm_file`
- `docker cp architecture-bionicpro-keycloak-1:/tmp/keycloak-results-export.json ./keycloak/keycloak-results-export.json`