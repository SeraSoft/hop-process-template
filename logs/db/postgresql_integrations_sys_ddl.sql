drop database if exists integrations_sys;
drop user if exists integrations_user;

CREATE USER integrations_user PASSWORD 'password';

CREATE DATABASE integrations WITH OWNER = integration_user ENCODING = 'UTF8' TABLESPACE = pg_default;

GRANT ALL PRIVILEGES ON DATABASE integrations to integrations_user;

\connect integrations;

CREATE SCHEMA IF NOT EXISTS config;

CREATE TABLE config.integrations_processes (
	id varchar(32) NOT NULL,
	short_name varchar(32) NOT NULL,
	description varchar(1024) NULL,
	project varchar(64) NOT NULL,
	is_active bpchar(1) NOT NULL DEFAULT 'Y'::bpchar,
	CONSTRAINT integration_processes_pk PRIMARY KEY (id)
);
-- Column comments

COMMENT ON COLUMN config.integrations_processes.id IS 'This is the process code we use to start PDI processes. Passed with p_program_name.';
COMMENT ON COLUMN config.integrations_processes.short_name IS 'Self explanatory, short, description of the process';
COMMENT ON COLUMN config.integrations_processes.project IS 'Project''s code reference for this process. Must be present in configuration file as pdi.project.code';
COMMENT ON COLUMN config.integrations_processes.is_active IS 'Indicate if the process is active or not. Values: Y, N';

CREATE TABLE config.integrations_log_events (
	id varchar(48) NOT NULL,
	event_type char(1) NOT NULL,  -- E -> Errore, I -> Information, W -> Warning
	category varchar(64) NOT NULL,
	sub_category varchar(64) NULL,
	gravity integer NOT NULL default(0),
	CONSTRAINT integration_log_events_pk PRIMARY KEY (id)
);

CREATE TABLE config.integrations_log_event_messages (
	id varchar(48) NOT NULL,
	lang char(5) NOT NULL DEFAULT 'it_IT',   
	integration_log_event_id varchar(48) NOT NULL REFERENCES config.integrations_log_events (id),
	message_text text NULL,
	CONSTRAINT integration_log_event_messages_pk PRIMARY KEY (id)
);

CREATE SCHEMA IF NOT EXISTS log;

CREATE TABLE log.integrations_logs (
	id varchar(48) not null,
	integration_process_id varchar(32) NOT NULL REFERENCES config.integrations_processes (id),
	proc_status char(1) NOT NULL,
	max_gravity integer default(0),
	date_started timestamp NOT NULL,
	date_finished timestamp NULL,
	log_file_ref varchar(255) NOT NULL,
	username varchar(32) NULL,
	host varchar(64) NULL,
	CONSTRAINT integration_log_px PRIMARY KEY (id)
);

CREATE TABLE log.integrations_log_details (
	id varchar(48) not null,
	integration_log_id varchar(48) NOT NULL REFERENCES log.integrations_logs (id),
	source_sys_code varchar(32),
	source_sys_row_ref varchar(50),
	integration_log_event_id varchar(32) NOT NULL REFERENCES config.integrations_log_events (id),
	entity varchar(64),
	message_details varchar(50),
	CONSTRAINT integration_log_detail_pk PRIMARY KEY (Id)
);

INSERT INTO config.integrations_log_events (id,event_type,category,sub_category,gravity) VALUES
	 ('SYS001','H','SYSTEM','EXCEPTIONS',10);
INSERT INTO config.integrations_log_event_messages (id,lang,integration_log_event_id,message_text) VALUES
	 ('SYS0001','it_IT','SYS001','Si è verificato un errore si sistema non gestito durante l''esecuzione della procedura. Controlla il log per i dettagli'),
	 ('SYS0002','en_US','SYS001','Unhandled error occured during process execution. Check the log for further details.');	 