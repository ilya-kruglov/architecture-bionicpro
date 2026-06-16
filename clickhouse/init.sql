CREATE DATABASE IF NOT EXISTS reports;

CREATE TABLE IF NOT EXISTS reports.crm_events
(
    payload String
) ENGINE = Kafka()
SETTINGS
    kafka_broker_list = 'kafka:9092',
    kafka_topic_list = 'crm.public.customers',
    kafka_group_name = 'clickhouse_consumer_final',
    kafka_format = 'JSONEachRow',
    kafka_num_consumers = 1;

CREATE MATERIALIZED VIEW IF NOT EXISTS reports.customers_mv
ENGINE = ReplacingMergeTree ORDER BY (id)
AS SELECT
    JSONExtractString(JSONExtractString(payload, 'after'), 'id') AS id,
    JSONExtractString(JSONExtractString(payload, 'after'), 'name') AS name,
    JSONExtractString(JSONExtractString(payload, 'after'), 'email') AS email,
    toDateTime(JSONExtractInt(JSONExtractString(payload, 'after'), 'created_at') / 1000000) AS created_at,
    toDateTime(JSONExtractInt(JSONExtractString(payload, 'after'), 'updated_at') / 1000000) AS updated_at,
    JSONExtractString(payload, 'op') AS operation,
    JSONExtractInt(payload, 'ts_ms') / 1000 AS event_time
FROM reports.crm_events
WHERE JSONExtractString(payload, 'op') IN ('c', 'u') AND JSONExtractString(JSONExtractString(payload, 'after'), 'id') != '';