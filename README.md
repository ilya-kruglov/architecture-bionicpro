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

## Задание 2.1: Архитектура решения для подготовки и получения отчётов
![Архитектура сервиса отчётов](diagrams/task2_1-architecture.png)
### Описание компонентов
- **CRM (Битрикс24)** – источник данных о клиентах.
- **База данных (PostgreSQL)** – хранилище телеметрии с протезов.
- **Apache Airflow** – ETL-оркестратор, запускается по расписанию (`0 2 * * *`), извлекает данные из CRM и БД, трансформирует и загружает в ClickHouse.
- **ClickHouse** – OLAP-база данных, содержит витрину `reports_mv` с агрегированными отчётами по пользователям.
- **API (бэкенд)** – предоставляет эндпоинт `/reports`, который по сессионной cookie определяет пользователя и возвращает только его собственные данные из ClickHouse.
- **Web Frontend (React)** – кнопка «Download Report» вызывает `/reports` и отображает полученные данные.
### Примечание
ETL-процесс запускается ежедневно в 2:00, поэтому отчёт содержит только данные, уже обработанные Airflow.

## Задание 3: Снижение нагрузки на базу данных
Добавлены:
- Minio (S3-совместимое хранилище) для сохранения сгенерированных отчётов.
- Nginx как CDN с кешированием статических файлов отчётов.
- В API-сервисе реализована логика: при запросе отчёта сначала проверяется наличие в S3, если есть – отдаётся ссылка на CDN, если нет – генерируется, сохраняется в S3 и возвращается ссылка.
- Структура хранения: `reports/{user_id}/{period}.json`.
- Кеш в Nginx инвалидируется по времени (60 минут) или при обновлении отчёта (можно расширить).

## Задание 4: Повышение оперативности и стабильности работы CRM
Реализован CDC (Change Data Capture) пайплайн для асинхронной репликации изменений из CRM-базы данных в ClickHouse. Это позволяет разделить OLTP-нагрузку на CRM и аналитические запросы, исключив влияние массовых выгрузок на транзакционную работу системы.

### Архитектура решения
1. **CRM Database (PostgreSQL)** – источник данных, на котором включена логическая репликация (`wal_level=logical`).
2. **Debezium (Kafka Connect)** – захватывает изменения (INSERT, UPDATE, DELETE) из таблиц `customers` и `orders` (и других) и публикует их в топики Kafka.
3. **Apache Kafka** – центральный брокер сообщений, хранит события изменений.
4. **ClickHouse** – через движок `KafkaEngine` потребляет события из топиков и строит материализованные представления (витрины), объединяющие данные CRM с телеметрией.
5. **API (auth-service)** – переключен на использование новой витрины `reports.report_mv`, что обеспечивает доступ к актуальным данным без обращения к CRM.

### Стек и компоненты
- **PostgreSQL (crm_db)** – порт `5434`, БД `crm`, пользователь `crm_user` / пароль `crm_password`.
- **Zookeeper** – координация Kafka.
- **Kafka** – порт `9092`, брокер сообщений.
- **Kafka Connect (Debezium)** – порт `8083`, REST API для управления коннекторами.
- **ClickHouse** – порты `8123` (HTTP) и `9000` (Native), БД `reports`.

### Настройка и запуск
#### 1. Запуск контейнеров
Если не было изменений в файлах:
- `docker compose up -d`
Если вы вносили изменения в код (например, в `auth-service/main.py`, `frontend/src/...`, `airflow/dags/...`), то:
- `docker compose up -d --build`
Проверьте, что все сервисы запущены:
- `docker ps`
В списке должны быть: `keycloak_db`, `keycloak`, `frontend`, `redis`, `auth`, `openldap`, `clickhouse`, `airflow-postgres`, `airflow-webserver`, `airflow-scheduler`, `minio`, `nginx-cdn`, `crm_db`, `zookeeper`, `kafka`, `kafka-connect`.
##### Проверка доступности сервисов
- **Keycloak:** `http://localhost:8080` → должна открыться страница входа (admin/admin).
- **Frontend:** `http://localhost:3000` → страница с кнопкой Login.
- **Auth:** `http://localhost:8000/auth/user` → должен вернуть 401 (если нет куки) – это нормально.
- **Airflow:** `http://localhost:8081` → логин admin/admin.
- **Minio:** `http://localhost:9002` → логин minioadmin/minioadmin.
- **Kafka Connect:** `http://localhost:8083/connectors` → должно вернуть пустой JSON-список (или ошибку, если ещё не запущен – подождите немного).

#### 2. Инициализация ClickHouse
Выполните скрипт создания таблиц и витрин:
- `docker exec -i architecture-bionicpro-clickhouse-1 clickhouse-client --multiquery < clickhouse/init.sql`
Либо зайдите в клиент и выполните команды вручную:
- `docker exec -it architecture-bionicpro-clickhouse-1 clickhouse-client`
Затем вставьте поочерёдно каждую команду из clickhouse/init.sql, завершая каждую точкой с запятой.

#### 3. Загрузка конфигурации Debezium-коннектора
После полного запуска всех сервисов (подождите 20–30 секунд) выполните:
- `curl -X POST -H "Content-Type: application/json" --data @debezium/connector.json http://localhost:8083/connectors`
Проверьте статус коннектора:
- `curl http://localhost:8083/connectors/crm-connector/status | jq`
Должен быть статус (state) `RUNNING`.

#### 4. Создание таблиц в CRM
Подключитесь к контейнеру `crm_db` и выполните SQL-скрипт:
- `docker exec -it architecture-bionicpro-crm_db-1 psql -U crm_user -d crm`
Внутри оболочки `psql` выполните:
```sql
CREATE TABLE customers (
    id VARCHAR PRIMARY KEY,
    name VARCHAR,
    email VARCHAR,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE orders (
    id VARCHAR PRIMARY KEY,
    customer_id VARCHAR REFERENCES customers(id),
    amount DECIMAL(10,2),
    created_at TIMESTAMP DEFAULT NOW()
);
```
- Выйдите из `psql` (`\q`).

#### 5. Проверка работы CDC
Вставьте тестовую запись в CRM:
- `docker exec -it architecture-bionicpro-crm_db-1 psql -U crm_user -d crm -c "INSERT INTO customers (id, name, email) VALUES ('1', 'Test User', 'test@example.com');"`
Через несколько секунд проверьте, что запись появилась в витрине (материализованном представлении):
- `docker exec -it architecture-bionicpro-clickhouse-1 clickhouse-client -q "SELECT * FROM reports.customers_mv"`
Если вы видите строку с данными тестового пользователя – CDC работает корректно.

#### 6. Остановка стека
Чтобы корректно остановить все контейнеры без потери данных:
- `docker compose down`
Если нужно полностью очистить все данные (volumes) – используйте:
- `docker compose down -v`
Но тогда потеряются все накопленные данные (сессии, БД, телеметрия, отчёты в Minio и т.д.). 

#### 7. НЕОБЯЗАТЕЛЬНО: Удаление примонтированных папок на хосте (bind mounts)
- `sudo rm -rf ./crm-data ./postgres-keycloak-data ./minio-data ./airflow-postgres ./ldap-data`