from datetime import datetime, timedelta
from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.providers.postgres.hooks.postgres import PostgresHook
from clickhouse_driver import Client

default_args = {
    'owner': 'bionicpro',
    'depends_on_past': False,
    'start_date': datetime(2026, 6, 15),
    'retries': 1,
    'retry_delay': timedelta(minutes=5),
}


def extract_crm(**context):
    """Извлечение данных о клиентах из CRM (Битрикс24 через API или DB)"""
    # Здесь заглушка – в реальности вызов API CRM
    # В учебных целях используем PostgresHook для тестовой БД
    pg_hook = PostgresHook(postgres_conn_id='crm_db')
    sql = "SELECT id, name, email FROM customers WHERE updated_at > %(last_run)s"
    # Используем контекст для передачи данных между задачами
    data = pg_hook.get_pandas_df(sql, parameters={'last_run': '2026-01-01'})
    context['ti'].xcom_push(key='crm_data', value=data.to_dict('records'))


def extract_telemetry(**context):
    """Извлечение телеметрии из PostgreSQL (База данных)"""
    pg_hook = PostgresHook(postgres_conn_id='telemetry_db')
    sql = """
        SELECT user_id, device_id, timestamp, signal_strength, battery_level, movement_type
        FROM telemetry
        WHERE timestamp >= NOW() - INTERVAL '1 day'
    """
    data = pg_hook.get_pandas_df(sql)
    context['ti'].xcom_push(key='telemetry_data', value=data.to_dict('records'))


def transform_and_load(**context):
    """Трансформация и загрузка в ClickHouse (витрина)"""
    crm_data = context['ti'].xcom_pull(key='crm_data', task_ids='extract_crm')
    telemetry_data = context['ti'].xcom_pull(key='telemetry_data', task_ids='extract_telemetry')

    # Агрегация телеметрии по user_id
    # ... логика объединения

    client = Client(host='clickhouse', port=9000, user='default', password='')
    # Создание таблицы витрины если не существует
    client.execute('''
        CREATE TABLE IF NOT EXISTS reports.reports_mv (
            user_id String,
            report_date Date,
            total_signals UInt32,
            avg_battery Float32,
            unique_movements UInt8,
            customer_name String,
            customer_email String
        ) ENGINE = SummingMergeTree()
        ORDER BY (user_id, report_date)
    ''')

    # Вставка данных

    # Для примера вставляем одну запись
    client.execute(
        'INSERT INTO reports.reports_mv VALUES',
        [('prothetic1', datetime.now().date(), 1234, 85.5, 5, 'Prothetic One', 'prothetic1@example.com')]
    )


with DAG(
    'reports_etl',
    default_args=default_args,
    description='ETL for reports from CRM and telemetry',
    schedule_interval='0 2 * * *',  # каждый день в 2:00
    catchup=False,
) as dag:

    t1 = PythonOperator(
        task_id='extract_crm',
        python_callable=extract_crm,
        provide_context=True,
    )
    t2 = PythonOperator(
        task_id='extract_telemetry',
        python_callable=extract_telemetry,
        provide_context=True,
    )
    t3 = PythonOperator(
        task_id='transform_and_load',
        python_callable=transform_and_load,
        provide_context=True,
    )

    [t1, t2] >> t3
