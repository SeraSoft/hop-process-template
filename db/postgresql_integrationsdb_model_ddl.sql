-------------------------------------------------------
-- Data model DDL for integrations_db 
-- Rel. 4.0
-------------------------------------------------------

-- drop database if exists integrations_db;
-- drop user if exists di_sys_user;

-- CREATE USER di_sys_user PASSWORD 'password';

-- CREATE DATABASE integrations_db WITH OWNER di_sys_user TEMPLATE='template0' ENCODING = 'UTF8';

-- \connect integrations_db;
CREATE SCHEMA IF NOT EXISTS config;

CREATE SCHEMA IF NOT EXISTS logs;

CREATE  TABLE config.event_category ( 
	id                   varchar(48)  NOT NULL  ,
	name                 varchar(64)  NOT NULL  ,
	event_type           char(1)  NOT NULL  ,
	CONSTRAINT pk_integrations_log_event_subcategory_0 PRIMARY KEY ( id )
 );

CREATE  TABLE config.event_subcategory ( 
	id                   varchar(48)  NOT NULL  ,
	name                 varchar(64)  NOT NULL  ,
	event_category_id    varchar(48)  NOT NULL  ,
	CONSTRAINT pk_integrations_log_event_subcategory PRIMARY KEY ( id )
 );

CREATE  TABLE config.integrations_processes ( 
	id                   varchar(48)  NOT NULL  ,
	short_name           varchar(32)  NOT NULL  ,
	description          varchar(1024)    ,
	project              varchar(64)  NOT NULL  ,
	is_active            char(1) DEFAULT 'Y'::bpchar NOT NULL,
	process_lock       char(1) DEFAULT 'S'::bpchar NOT NULL,
	last_instance_started_at timestamp,
	CONSTRAINT integrations_processes_pk PRIMARY KEY ( id )
 );

CREATE  TABLE logs.integrations_logs ( 
	id                   varchar(48)  NOT NULL  ,
	integrations_processes_id varchar(48)  NOT NULL  ,
	proc_status          char(1)  NOT NULL  ,
	max_gravity          integer DEFAULT 0   ,
	date_started         timestamp  NOT NULL  ,
	date_finished        timestamp    ,
	log_file_ref         varchar(255)  NOT NULL  ,
	username             varchar(32)    ,
	"host"               varchar(64)    ,
	CONSTRAINT integrations_log_px PRIMARY KEY ( id )
 );

CREATE  TABLE logs.integrations_log_events ( 
	id                   varchar(48)  NOT NULL  ,
	integrations_logs_id varchar(48)  NOT NULL  ,
	date_event           date DEFAULT CURRENT_DATE NOT NULL  ,
	source_sys_code      varchar(32)    ,
	source_sys_row_ref   varchar(50)    ,
	event_subcategory_id varchar(32)  NOT NULL  ,
	gravity              integer DEFAULT 0 NOT NULL  ,
	event_text           text  NOT NULL  ,
	event_data           text    ,
	CONSTRAINT integrations_log_detail_pk PRIMARY KEY ( id )
 );

ALTER TABLE config.event_subcategory ADD CONSTRAINT fk_event_category FOREIGN KEY ( event_category_id ) REFERENCES config.event_category( id );

ALTER TABLE logs.integrations_log_events ADD CONSTRAINT integrations_log_details_integrations_logs_id_fkey FOREIGN KEY ( integrations_logs_id ) REFERENCES logs.integrations_logs( id );

ALTER TABLE logs.integrations_log_events ADD CONSTRAINT fk_integrations_log_events_event_subcategory FOREIGN KEY ( event_subcategory_id ) REFERENCES config.event_subcategory( id );

ALTER TABLE logs.integrations_logs ADD CONSTRAINT integrations_logs_integrations_processes_id_fkey FOREIGN KEY ( integrations_processes_id ) REFERENCES config.integrations_processes( id );

COMMENT ON COLUMN config.integrations_processes.id IS 'This is the process code we use to start HOP processes. Passed with p_program_name.';

COMMENT ON COLUMN config.integrations_processes.short_name IS 'Self explanatory, short, description of the process';

COMMENT ON COLUMN config.integrations_processes.project IS 'Project''s code reference for this process. Must be present in configuration file as hop.project.code';

COMMENT ON COLUMN config.integrations_processes.is_active IS 'Indicate if the process is active or not. Values: Y, N';

COMMENT ON COLUMN logs.integrations_logs.integrations_processes_id IS 'Reference to the started process.';

INSERT INTO config.event_category (id,event_type, name) VALUES
	 ('SYS001','E','SYSTEM EXCEPTION');
INSERT INTO config.event_subcategory (id, name, event_category_id) VALUES
	 ('SYSGE001','GENERIC ERROR', 'SYS001');


INSERT INTO config.integrations_processes (id, short_name, description, project, is_active) VALUES
	 ('default','Default project', 'This is a sample project called default', 'hop-template', 'Y');