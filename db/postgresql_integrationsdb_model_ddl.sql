-------------------------------------------------------
-- Data model DDL for integrations_db 
-- Rel. 4.2
-------------------------------------------------------

-- drop database if exists integrations_db;
-- drop user if exists di_sys_user;

-- CREATE USER di_sys_user PASSWORD 'password';

-- CREATE DATABASE integrations_db WITH OWNER di_sys_user TEMPLATE='template0' ENCODING = 'UTF8';

-- \connect integrations_db;
CREATE SCHEMA IF NOT EXISTS config;

CREATE SCHEMA IF NOT EXISTS logs;

CREATE  TABLE config.distribution_list ( 
	id                   varchar(48)  NOT NULL  ,
	code                 varchar(32)  NOT NULL  ,
	description          varchar(1024)    ,
	is_active            char(1) DEFAULT 'Y' NOT NULL  ,
	created_at           timestamp DEFAULT CURRENT_TIMESTAMP NOT NULL  ,
	updated_at           timestamp DEFAULT CURRENT_TIMESTAMP NOT NULL  ,
	CONSTRAINT unq_distribution_list_id UNIQUE ( id ) 
 );

CREATE  TABLE config.distribution_list_user ( 
	id                   varchar(48)  NOT NULL  ,
	name                 varchar(128)  NOT NULL  ,
	address              varchar(256)  NOT NULL  ,
	is_active            char(1) DEFAULT 'Y' NOT NULL  ,
	updated_at           timestamp DEFAULT CURRENT_TIMESTAMP NOT NULL  ,
	created_at           timestamp DEFAULT CURRENT_TIMESTAMP NOT NULL  ,
	CONSTRAINT unq_distribution_list_user_id UNIQUE ( id ) 
 );

CREATE  TABLE config.email_channel ( 
	id                   varchar(48)  NOT NULL  ,
	is_authenticated     char(1) DEFAULT 'Y' NOT NULL  ,
	smtp_host            varchar(64)  NOT NULL  ,
	smtp_port            integer DEFAULT 25 NOT NULL  ,
	smtp_user            varchar(64)    ,
	smtp_user_pwd        varchar(64)    ,
	is_secure            char(1) DEFAULT 'N' NOT NULL  ,
	secure_protocol      varchar(32) DEFAULT 'NONE' NOT NULL  ,
	is_active            char(1) DEFAULT 'Y' NOT NULL  ,
	created_at           timestamp DEFAULT CURRENT_TIMESTAMP NOT NULL  ,
	updated_at           timestamp DEFAULT CURRENT_TIMESTAMP NOT NULL  ,
	CONSTRAINT pk_email_channel PRIMARY KEY ( id )
 );

CREATE  TABLE config.email_message ( 
	id                   varchar(48)  NOT NULL  ,
	subject              varchar(128)  NOT NULL  ,
	created_at           timestamp DEFAULT CURRENT_TIMESTAMP NOT NULL  ,
	updated_at           timestamp DEFAULT CURRENT_TIMESTAMP NOT NULL  ,
	CONSTRAINT pk_email_message PRIMARY KEY ( id )
 );

CREATE  TABLE config.event_category ( 
	id                   varchar(48)  NOT NULL  ,
	name                 varchar(64)  NOT NULL  ,
	event_type           char(1)  NOT NULL  ,
	is_active            char(1) DEFAULT 'Y' NOT NULL  ,
	created_at           timestamp DEFAULT CURRENT_TIMESTAMP NOT NULL  ,
	updated_at           timestamp DEFAULT CURRENT_TIMESTAMP NOT NULL  ,
	CONSTRAINT pk_integrations_log_event_subcategory_0 PRIMARY KEY ( id )
 );

CREATE  TABLE config.event_subcategory ( 
	id                   varchar(48)  NOT NULL  ,
	name                 varchar(64)  NOT NULL  ,
	event_category_id    varchar(48)  NOT NULL  ,
	is_active            char(1) DEFAULT 'Y' NOT NULL  ,
	created_at           timestamp DEFAULT CURRENT_TIMESTAMP NOT NULL  ,
	updated_at           timestamp DEFAULT CURRENT_TIMESTAMP NOT NULL  ,
	CONSTRAINT pk_integrations_log_event_subcategory PRIMARY KEY ( id )
 );

CREATE  TABLE config.integrations_processes ( 
	id                   varchar(48)  NOT NULL  ,
	short_name           varchar(32)  NOT NULL  ,
	description          varchar(1024)    ,
	project              varchar(64)  NOT NULL  ,
	project_subfolder    varchar(128)    ,
	main_worflow         varchar(128)    ,
	process_lock         char(1) DEFAULT 'N' NOT NULL  ,
	previous_instance_started_at timestamp  ,
	max_rows             integer    ,
	is_active            char(1) DEFAULT 'Y' NOT NULL  ,
	created_at           timestamp DEFAULT CURRENT_TIMESTAMP NOT NULL  ,
	updated_at           timestamp DEFAULT CURRENT_TIMESTAMP NOT NULL  ,
	CONSTRAINT integrations_processes_pk PRIMARY KEY ( id )
 );

CREATE  TABLE config.notification_channel ( 
	id                   varchar(48)  NOT NULL  ,
	code                 varchar(32)  NOT NULL  ,
	description          varchar(1024)    ,
	channel_type         varchar(32) DEFAULT 'EMAIL' NOT NULL  ,
	is_active            char(1) DEFAULT 'Y' NOT NULL  ,
	created_at           timestamp DEFAULT CURRENT_TIMESTAMP NOT NULL  ,
	updated_at           timestamp DEFAULT CURRENT_TIMESTAMP NOT NULL  ,
	CONSTRAINT pk_notification_channel PRIMARY KEY ( id )
 );

CREATE  TABLE config.process_notification ( 
	integration_process_id varchar(48)  NOT NULL  ,
	code                 varchar(64)  NOT NULL  ,
	description          varchar(1024)    ,
	notification_type    char(1)  NOT NULL  ,
	notification_channel_id varchar(48)  NOT NULL  ,
	from_label           varchar(256)    ,
	from_address         varchar(256)    ,
	subject              varchar(256)    ,
	message              text  NOT NULL  ,
	distribution_list_id varchar(48)  NOT NULL  ,
	is_active            char(1) DEFAULT 'Y' NOT NULL  ,
	created_at           timestamp DEFAULT CURRENT_TIMESTAMP NOT NULL  ,
	updated_at           timestamp DEFAULT CURRENT_TIMESTAMP NOT NULL  
 );

CREATE  TABLE config.distribution_list_entries ( 
	distribution_list_id varchar(48)  NOT NULL  ,
	distribution_list_user_id varchar(48)  NOT NULL  ,
	updated_at           timestamp DEFAULT CURRENT_TIMESTAMP NOT NULL  ,
	created_at           timestamp DEFAULT CURRENT_TIMESTAMP NOT NULL  
 );

CREATE  TABLE logs.integrations_logs ( 
	id                   varchar(48)  NOT NULL  ,
	integrations_processes_id varchar(48)  NOT NULL  ,
	proc_status          char(1)  NOT NULL  ,
	max_gravity          integer DEFAULT 0 NOT NULL  ,
	date_started         timestamp DEFAULT CURRENT_TIMESTAMP NOT NULL  ,
	date_finished        timestamp    ,
	log_file_ref         varchar(255) DEFAULT 'LMS' NOT NULL  ,
	username             varchar(32)    ,
	"host"               varchar(64)    ,
	CONSTRAINT integrations_log_px PRIMARY KEY ( id )
 );

CREATE  TABLE logs.integrations_log_events ( 
	id                   varchar(48)  NOT NULL  ,
	date_event           date DEFAULT CURRENT_DATE NOT NULL  ,
	integrations_logs_id varchar(48)  NOT NULL  ,
	source_sys_code      varchar(32)    ,
	event_subcategory_id varchar(32)  NOT NULL  ,
	gravity              integer DEFAULT 0 NOT NULL  ,
	event_text           text  NOT NULL  ,
	event_data           text    ,
	CONSTRAINT integrations_log_detail_pk PRIMARY KEY ( id )
 );

ALTER TABLE config.distribution_list_entries ADD CONSTRAINT fk_distribution_list_entries_distribution_list FOREIGN KEY ( distribution_list_id ) REFERENCES config.distribution_list( id );

ALTER TABLE config.distribution_list_entries ADD CONSTRAINT fk_distribution_list_entries_distribution_list_user FOREIGN KEY ( distribution_list_user_id ) REFERENCES config.distribution_list_user( id );

ALTER TABLE config.event_subcategory ADD CONSTRAINT fk_event_category FOREIGN KEY ( event_category_id ) REFERENCES config.event_category( id );

ALTER TABLE config.notification_channel ADD CONSTRAINT fk_notification_channel_email_channel FOREIGN KEY ( id ) REFERENCES config.email_channel( id );

ALTER TABLE config.process_notification ADD CONSTRAINT fk_process_notification_notification_channel FOREIGN KEY ( notification_channel_id ) REFERENCES config.notification_channel( id );

ALTER TABLE config.process_notification ADD CONSTRAINT fk_process_notification_integrations_processes FOREIGN KEY ( integration_process_id ) REFERENCES config.integrations_processes( id );

ALTER TABLE config.process_notification ADD CONSTRAINT fk_process_notification_distribution_list FOREIGN KEY ( distribution_list_id ) REFERENCES config.distribution_list( id );

ALTER TABLE logs.integrations_log_events ADD CONSTRAINT integrations_log_details_integrations_logs_id_fkey FOREIGN KEY ( integrations_logs_id ) REFERENCES logs.integrations_logs( id );

ALTER TABLE logs.integrations_log_events ADD CONSTRAINT fk_integrations_log_events_event_subcategory FOREIGN KEY ( event_subcategory_id ) REFERENCES config.event_subcategory( id );

ALTER TABLE logs.integrations_logs ADD CONSTRAINT integrations_logs_integrations_processes_id_fkey FOREIGN KEY ( integrations_processes_id ) REFERENCES config.integrations_processes( id );

COMMENT ON COLUMN config.email_channel.secure_protocol IS 'NONE, SSL, TLS, TLSv1.2';

COMMENT ON COLUMN config.integrations_processes.id IS 'This is the process code we use to start HOP processes. Passed with p_program_name.';

COMMENT ON COLUMN config.integrations_processes.short_name IS 'Self explanatory, short, description of the process';

COMMENT ON COLUMN config.integrations_processes.project IS 'Project''s code reference for this process. Must be present in configuration file as hop.project.code';

COMMENT ON COLUMN config.integrations_processes.project_subfolder IS 'Name of the project''s subfolder';

COMMENT ON COLUMN config.integrations_processes.main_worflow IS 'Name of the main workflowto be started to run the process';

COMMENT ON COLUMN config.integrations_processes.process_lock IS 'Handle a process lock to manage concurrent execution. Values: Y, N';

COMMENT ON COLUMN config.integrations_processes.max_rows IS 'If set, states a maximum number of rows that can be transferred to a target table or system (experimental)';

COMMENT ON COLUMN config.integrations_processes.is_active IS 'Indicate if the process is active or not. Values: Y, N';

COMMENT ON COLUMN config.notification_channel.code IS 'Mnemonic code to identify a channel to use to notify something to someone';

COMMENT ON COLUMN config.notification_channel.channel_type IS 'Use only EMAIL for now. Open to other channel types on the future';

COMMENT ON COLUMN config.process_notification.code IS 'Mnemonic code assigned to this notification entry. Used by Hop to retrieve it in whenever needed.';

COMMENT ON COLUMN config.process_notification.notification_type IS 'Information -> I, Error -> E, Warning -> W';

COMMENT ON COLUMN config.process_notification.notification_channel_id IS 'Channel used to send the notification to users';

COMMENT ON COLUMN logs.integrations_logs.integrations_processes_id IS 'Reference to the started process. Correlates this data stream with Hop logs in files or LMS systems';

COMMENT ON COLUMN logs.integrations_logs.proc_status IS 'R: Running, S: Stopped, E: In Error (related to the last execution)';

COMMENT ON COLUMN logs.integrations_logs.max_gravity IS 'Max gravity happened during the execution of this run';

COMMENT ON COLUMN logs.integrations_logs.date_started IS 'Start process timestamp';

COMMENT ON COLUMN logs.integrations_logs.date_finished IS 'Process termination  timestamp';

COMMENT ON COLUMN logs.integrations_logs.log_file_ref IS 'Reference to the project logfile. Set to LMS (default) in case an LMS system is used';

COMMENT ON COLUMN logs.integrations_log_events.date_event IS 'The date this event occurred';

COMMENT ON COLUMN logs.integrations_log_events.integrations_logs_id IS 'Reference to the running process';

COMMENT ON COLUMN logs.integrations_log_events.source_sys_code IS 'Reference to the system that originates the row, source of the event (if any otherwise null if the event is just an information msg)';

COMMENT ON COLUMN logs.integrations_log_events.gravity IS 'Sets a level of gravity of the current event. Valid values: 0 - 10. Default: 0 -> Generic info';

COMMENT ON COLUMN logs.integrations_log_events.event_text IS 'Custom message describing the event happend or tracked';

COMMENT ON COLUMN logs.integrations_log_events.event_data IS 'Support data related to the event tracked';

INSERT INTO config.event_category (id,event_type, name) VALUES
	 ('SYS001','E','SYSTEM EXCEPTION');
INSERT INTO config.event_subcategory (id, name, event_category_id) VALUES
	 ('SYSGE001','GENERIC ERROR', 'SYS001');