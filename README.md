# Hop's Process Template

Apache Hop Process template is a mature seed that you can use as a base to develop your Apache Hop processes the correct way.

Features implemented and enforced by the template are:

- **Clear directory structure** for code, tests, and configuration files. 
This template gives a Hop project a predefined structure to manage configuration files and process from within a same bundle that can easily be distributed.
- **Single process execution**: if a process instance, same as the one is trying to start, is already executing the new instance will not start. We are used to say that when   
- **Single point for errors' management**: as a good methodological approach the template try to force the management of events and errors in a single point
- **Integration tests enablement**: the template gives you the possibility to easily structure a tests strategy for your code by injecting custom code in your pipelines/workflows structure
- **Event logs structure enable to qoprational analysis**

## Setup
### Hop process template setup


### Hop process support database creation
 
#### Liquibase installation 

We adopt Liquibase in order to keep `config` and `logs` tables up-to-date.

#### Database creation

#### Database update upon changes
1. In case of brand new database (fresh installation)

```powershell
liquibase update \
    --url="jdbc:postgresql://localhost:5432/hop" \
    --changeLogFile="master.xml" \
    --username="hop" \
    --password="password" \
```

2. While, if your database already exists (existing environments):

```powershell
liquibase changelogSync \
    --url="jdbc:postgresql://localhost:5432/hop" \
    --changeLogFile="master.xml" \
    --username="hop" \
    --password="password"
```

In both cases, replace `url`, `username` and `password` with the actual ones.

## Hop process template environment variables

| Nome variabile      | Descrizione                         | Valori di default |
|---------------|-------------------------------------|---------------|
|project.link.ref|| \${PROJECT_HOME}/src/project/main/${p_base_process_name} |
|hop.user||hopuser|
|hop.program.name||hop|
|sys.unhandled.exception.subcategory.generic||SYSGE001|
|integrations.db.config.schema||config|
|integrations.db.log.schema||logs|
|integrations.db.host||localhost|
|integrations.db.connection.name||integrations_db|
|integrations.db.name||integrations_db|
|integrations.db.port||5432|
|integrations.db.user||postgres|
|integrations.db.pwd||password|
|email.success.feedback.enabled||0|
|email.fail.feedback.enabled||1|
|mail.isauthenticated||0|
|mail.isgmail||0|
|smtp.mail.host|||
|smtp.mail.port|||
|smtp.mail.user|||
|smtp.mail.psw|||
|smtp.trusted.hosts|||
|smtp.check.server.identity|||
|mail.from.displayname||Hop Process Executor|
|mail.from.email||hopexecutor@maildomain.it|
|mail.subject||\[${v_hostname} - ${p_base_process_name}]|
|mail.subject.error||\${mail.subject} Failed for system exceptions|
|mail.subject.success||\${mail.subject} Terminated successfully|
|mail.subject.lock||\${mail.subject} Same instance is still running. Execution stopped.|
|mail.subject.application.error||\${mail.subject} Failed for application exceptions|
|default.mail.destination.addresses||destination@maildomain.it|
|success.mail.destination.addresses||\${default.mail.destination.addresses}|
|errors.mail.destination.addresses||\${default.mail.destination.addresses}|
|lock.mail.destination.addresses||\${default.mail.destination.addresses}|
|notactive.mail.destination.addresses||\${default.mail.destination.addresses}|
|application.error.mail.destination.addresses||\${default.mail.destination.addresses}|
|success.mail.text||The process ${p_base_process_name} running on server ${v_hostname} was terminated successfully. Execution's log file available at: ${p_logfile_name}. PLEASE DO NOT REPLAY TO THIS EMAIL!|
|error.mail.text||The process was terminated abnormally because of an Exception. Execution's log file available at: ${p_logfile_name}. PLEASE DO NOT REPLAY TO THIS EMAIL!|
|lock.mail.text||The process ${p_base_process_name} running on server ${v_hostname} can't be started because same process started at ${v_last_job_run_timestamp} is not yet terminated. Execution's log file available at: ${p_logfile_name}. PLEASE DO NOT REPLAY TO THIS EMAIL!|
|application.error.mail.text||During process's execution we collected some exceptions on integrations_log_details. The detailed list of exception is in the attachment to this email.<p>If needed, execution's log file is available at: ${p_logfile_name}. PLEASE DO NOT REPLAY TO THIS EMAIL!|
|notactive.mail.text||The process ${p_base_process_name} running on server ${v_hostname} can't be started because is set to not active. Execution's log file available at: ${p_logfile_name}. PLEASE DO NOT REPLAY TO THIS EMAIL!|

---
