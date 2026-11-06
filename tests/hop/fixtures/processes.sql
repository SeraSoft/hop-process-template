-- Test processes of the Hop lab (tests/hop/lab.sh up). 'default' comes from Liquibase.
INSERT INTO config.integrations_processes (id, short_name, description, project, is_active, is_running) VALUES
  ('vartest', 'vartest', 'Lab: logs the variables it receives', 'hop-process-template', 'Y', 'N'),
  ('6f1c2a8e-0d4b-4c39-9a57-3b2f0e5d7c11', 'uuidtest', 'Lab: id differs from short_name', 'hop-process-template', 'Y', 'N');
