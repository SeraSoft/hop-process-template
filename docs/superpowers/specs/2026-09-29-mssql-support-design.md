# Microsoft SQL Server support for the integrations database — design

## Goal

Let a template-based project use Microsoft SQL Server as `integrations_db`,
next to PostgreSQL and SQLite. The Liquibase changelog already supports SQL
Server (#33); the Hop side has no SQL Server connection metadata and no
SQL Server environment file, and the template has never been run on SQL Server.

## Context

- A database is selected by the environment: `config/template-<db>.json` sets
  `serasoft.integrations.db.connection.name` to the name of a connection in
  `metadata/rdbms/integrations_db_<db>.json`.
- Every database step of the template (4 Table Input, 3 Database Lookup,
  2 SQL, 2 Table Output, 2 Update) uses
  `${serasoft.integrations.db.connection.name}`.
- The six hand-written statements (Table Input and SQL actions) use ANSI SQL
  only (`COALESCE`, joins, `GROUP BY`, `UPDATE … WHERE … IN (SELECT …)`); they
  are expected to run unchanged on SQL Server, to be confirmed by the tests.
- Apache Hop 2.19.0 offers two SQL Server database plugins:
  - `MSSQLNATIVE`: Microsoft JDBC driver, `mssql-jdbc` 13.4.0 shipped in
    `lib/jdbc` of the `apache/hop:2.19.0` image, MIT licence;
  - `MSSQL`: jTDS driver, LGPL, not shipped. Not used.
- Customer SQL Server databases are reached with host + port and a SQL Server
  login (user + password); the integrations database is a dedicated database.

## Decisions

- **Approach:** one new connection metadata and one new environment file,
  following the existing per-database pattern. A single "Generic database"
  connection for all databases was rejected: Hop would lose the SQL Server
  dialect used to generate the SQL of Table Output, Update and Database Lookup.
- **Authentication:** SQL Server authentication only (user + password), host
  + port. No integrated Windows authentication, no named instances.
- **Encryption:** the Microsoft driver encrypts by default and validates the
  server certificate, which fails on self-signed certificates. Two environment
  variables drive the driver options:
  - `serasoft.integrations.db.mssql.encrypt` (template default `true`);
  - `serasoft.integrations.db.mssql.trust.server.certificate` (template
    default `true`; set it to `false` when the server has a certificate
    trusted by the JVM).

## Components

### `metadata/rdbms/integrations_db_mssql.json`

Connection `integrations_db_mssql`, plugin `MSSQLNATIVE`, access type native:

- `hostname`, `port`, `databaseName`, `username`, `password` from
  `serasoft.integrations.db.host`, `.port`, `.name`, `.user`, `.pwd`;
- `EXTRA_OPTION_MSSQLNATIVE.encrypt` = `${serasoft.integrations.db.mssql.encrypt}`;
- `EXTRA_OPTION_MSSQLNATIVE.trustServerCertificate` =
  `${serasoft.integrations.db.mssql.trust.server.certificate}`;
- the other attributes as in `integrations_db_postgres.json`, without the
  PostgreSQL-only `EXTRA_OPTION_POSTGRESQL.stringtype`.

**Fallback:** if Hop 2.19 does not resolve variables in extra options, the
connection uses a manual URL built from the same variables
(`jdbc:sqlserver://${serasoft.integrations.db.host}:${serasoft.integrations.db.port};databaseName=${serasoft.integrations.db.name};encrypt=${serasoft.integrations.db.mssql.encrypt};trustServerCertificate=${serasoft.integrations.db.mssql.trust.server.certificate}`).
The environment file does not change. Not needed in the end: the
`trust.server.certificate=false` run fails with `PKIX path building failed`,
so Hop 2.19 resolves the variables in the extra options.

### `config/template-mssql.json`

The eight variables of `template-postgresql.json`, with
`connection.name = integrations_db_mssql`, `port = 1433`, `user = sa`,
`name = integrations_db`, `host = localhost`, plus the two encryption
variables (`true`, `true`), each with a description.

### README

- Environment variables table: the two new variables; the
  `serasoft.integrations.db.connection.name` row lists the three connections
  (`integrations_db_postgres`, `integrations_db_sqlite`,
  `integrations_db_mssql`); the port row mentions `1433` for SQL Server.
- In the description of `serasoft.integrations.db.mssql.trust.server.certificate`:
  the connection stays encrypted but the server identity is not verified; set it
  to `false` when the server certificate is trusted.

No pipeline or workflow is changed. If a test shows a SQL Server
incompatibility, it is reported to the user before any fix.

## Verification

Live, with the lab harness outside the repo
(`/home/enrico/repositories/serasoft/airflow-lab/lab/hop-template-test`,
as for #26/#27), extended with a SQL Server environment:

- SQL Server 2022 in a throwaway container on the lab network;
  `integrations_db` created with `db/liquibase/master.xml`;
- Apache Hop 2.19.0 in a throwaway container, environment built from
  `config/template-mssql.json` with the SQL Server container as host;
  feedback emails disabled except the application-error one, sent to a
  Mailpit SMTP sink (test container);
- test-only processes in the throwaway copy of the template: `slowtest`
  (`WAITFOR DELAY` instead of `pg_sleep`) and one that records an application
  event in `integrations_log_events` for the running instance.

| Scenario | Expected |
|---|---|
| variables in the driver options | with `trust.server.certificate=false` the connection to the container (self-signed certificate) fails with a certificate error; with the template defaults it connects |
| normal run | exit 0; row `T`; `is_running = 'N'` |
| application error (event recorded) | exit 0; row `X`; the application-error email carries `logs.zip` with the execution CSV holding the event row (read back by the "Get logging_details" query) |
| lock present (`is_running` set to `'Y'` by hand) | exit 1; `SKIPPED: … is locked`; row `L`; `is_running` still `'Y'` |
| process paused (`is_active` not `Y`) | exit 1; `SKIPPED: … is not active`; no log row |
| run killed mid-execution, then `release_lock.hwf` | rows `R` become `K`; `is_running = 'N'`; next run exit 0 |

## Delivery

One GitHub issue, one branch from `main`, this spec and the implementation
plan committed on it, one PR closing the issue. `docs/` is not shipped in the
release ZIP.

## Results (2026-09-29, SQL Server 2022, Hop 2.19.0)

| Scenario | Result |
|---|---|
| baseline, no SQL Server connection | exit 1: `NullPointerException … "this.databaseMeta" is null` in `init_process_id.hpl` |
| variables in the driver options | `trust.server.certificate=false`: exit 1, `PKIX path building failed`; template defaults connect |
| normal run | exit 0; `T`; `is_running = 'N'` |
| application error | exit 0; `X`; 1 event; email `… Terminated successfully with application exceptions.` with `logs.zip` → CSV `SYSTEM EXCEPTION;GENERIC ERROR;5;TEST;row-1;apperrtest application event;` |
| lock present | exit 1; `SKIPPED: process 'default' is locked …`; `L`; `is_running` still `'Y'` |
| process paused | exit 1; `SKIPPED: process 'default' is not active`; no new row |
| killed run + `release_lock.hwf` | `R`/`Y` → release exit 0 → `K`/`N`; next run exit 0, `T` |

No template pipeline or workflow needed changes: the hand-written SQL runs unchanged on SQL Server.
