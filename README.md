# Hop's Process Template

Apache Hop Process template is a mature seed that you can use as a base to develop your Apache Hop processes the correct way.

Features implemented and enforced by the template are:

- **Clear directory structure** for code, tests, and configuration files. 
This template gives a Hop project a predefined structure to manage configuration files and process from within a same bundle that can easily be distributed.
- **Single process execution**: if a process instance, same as the one is trying to start, is already executing the new instance will not start. We are used to say that when   
- **Single point for errors' management**: as a good methodological approach the template try to force the management of events and errors in a single point
- **Integration tests enablement**: the template gives you the possibility to easily structure a tests strategy for your code by injecting custom code in your pipelines/workflows structure
- **Event logs structure enable to operational analysis**

We adopt Liquibase in order to keep `config` and `logs` tables up-to-date.

## Prerequisites
#### Liquibase installation 

To be able to create/update the support database conventionally named *integrations_db*, you must install liquibase on your computer. To properly install liquibase on your computer please refer to the installation procedure as specified [here]([here](https://docs.liquibase.com/start/install/home.html))

## Getting started
### Process template setup
TBD

### Support database creation
Remember, in both cases, replace `url`, `username` and `password` with the actual ones.
#### Database creation
In case of brand new database (fresh installation)

```powershell
liquibase update \
    --url="jdbc:postgresql://localhost:5432/integrations_db" \
    --changeLogFile="master.xml" \
    --username="postgres" \
    --password="password" 
```

#### Database update
While, if your database already exists (existing environments):

```powershell
liquibase changelogSync \
    --url="jdbc:postgresql://localhost:5432/integrations_db" \
    --changeLogFile="master.xml" \
    --username="postgres" \
    --password="password"
```

## Process template environment variables

The table below summarizes the set of base environment variables provided with the template. This set of variables will be the starting point of your application's environment variables. 

| Variabile Name      | Description                         | Default value |
|---------------|-------------------------------------|---------------|
|serasoft.project.link.ref|Link to activate the main process that must be started by the Hop Process Executor. The link is relative to the project home directory.| \${PROJECT_HOME}/src/project/main/${p_base_process_name} |
|serasoft.hop.user|The operating system user that will run the Hop Process execution. This user must have read/write permissions on the project home directory.|hopuser|
|serasoft.hop.program.name| A virtual name assigned to Apache Hop to be inserted in events logging tables as a reference for the running instance|hop|
|serasoft.sys.unhandled.exception.subcategory.generic|The generic subcategory for unhandled system exceptions. This is used to categorize exceptions in the logs.|SYSGE001|
|serasoft.integrations.db.config.schema|Name of the schema containing the configuration tables for the integrations database|config|
|serasoft.integrations.db.log.schema|Name of schema containing the logs tables for the integrations database|logs|
|serasoft.integrations.db.host|Name of the hosts where the integrations database is running. This can be an IP address or a hostname.|localhost|
|serasoft.integrations.db.connection.name|Name of the connection assigned in Apache Hop for the integrations database. This is used to connect to the database during Hop Process execution.|integrations_db|
|serasoft.integrations.db.name|Name of the database containing the configuration and logs tables for the integrations database|integrations_db|
|serasoft.integrations.db.port|Port of the integrations database. This is the port where the database server is listening for connections|5432|
|serasoft.integrations.db.user|Username used to connect to the integrations database. This user must have permissions to read/write in the specified database|postgres|
|serasoft.integrations.db.pwd|Password used to connect to the integrations database. This user must have permissions to read/write in the specified database|password|
|serasoft.email.success.feedback.enabled|Flag that enables or disables the sending of success feedback emails after a process execution. Set to 1 to enable, 0 to disable|0|
|serasoft.email.fail.feedback.enabled|Flag that enables or disables the sending of failure feedback emails after a process execution. Set to 1 to enable, 0 to disable|1|
|serasoft.email.application.error.feedback.enabled|Flag that enables or disables the sending of feedback emails after a process execution if application error. Set to 1 to enable, 0 to disable|1|
|serasoft.email.notactive.feedback.enabled|Flag that enables or disables the sending of feedback emails if the process is paused. Set to 1 to enable, 0 to disable|0|
|serasoft.email.lock.feedback.enabled|Flag that enables or disables the sending of feedback emails if the same process is alredy running. Set to 1 to enable, 0 to disable|1|
|serasoft.mail.isauthenticated|Flag to indicate if the SMTP server requires authentication. Set to true if authentication is needed, false otherwise|0|
|serasoft.mail.isgmail|Flag to indicate if the SMTP server is Gmail. Set to true if using Gmail, false otherwise|0|
|serasoft.smtp.mail.host|Name of the host where the SMTP server is running. This can be an IP address or a hostname||
|serasoft.smtp.mail.port|Port where the SMTP server is listening for connections|25|
|serasoft.smtp.mail.user|Username used to connect to SMTP server. This is used for authentication if the SMTP server requires it||
|serasoft.smtp.mail.psw|Password used to connect to SMTP server. This is used for authentication if the SMTP server requires it||
|serasoft.smtp.trusted.hosts|Comma-separated list of trusted hosts for the SMTP server. This can be used to allow connections from specific hosts without authentication||
|serasoft.smtp.check.server.identity|Flag to indiceate if the server identity should be checked when connecting to the SMTP server. Set to true to enable, false to disable||
|serasoft.mail.from.displayname|Label displayed in the 'From' field of the email. This is the name that will appear as the sender of the email.|Hop Process Executor|
|serasoft.mail.from.email|Email address used in the 'From' field of the email. This is the address that will appear as the sender of the email|hopexecutor@maildomain.it|
|serasoft.mail.subject|First part of the text displayed in the subject of the email. It includes the hostname and the base process name|\[${v_hostname} - ${p_base_process_name}]|
|serasoft.mail.subject.error|Text displayed in the subject of the email when an error occurs due to system exceptions. It includes the base process name.|\${serasoft.mail.subject} Failed for system exceptions|
|serasoft.mail.subject.success|Text displayed in the subject ot the email when the process execution is successful. It includes the base process name|\${serasoft.mail.subject} Terminated successfully|
|serasoft.mail.subject.lock|Text displayed in the subject ot the email when a lock occurs that prevents the process from executing. It includes the base process name|\${serasoft.mail.subject} Same instance is still running. Execution stopped.|
|serasoft.mail.subject.application.error|Text displayed in the subject of the email when application errors occurs during process execution. It includes the base process name.|\${serasoft.mail.subject} Terminated successfully with application exceptions.|
|serasoft.mail.subject.notactive|Text displayed in the subject ot the email when the process is paused. It includes the base process name!\${serasoft.mail.subject} This instance is paused. Execution not started.
|serasoft.default.mail.destination.addresses|Default set of email addresses to included wherever needed. Email addresses are separated by spaces|destination@maildomain.it|
|serasoft.success.mail.destination.addresses|Set of email addresses to send success feedback emails to. Email addresses are separated by spaces. It can includes the default addresses if needed. It defaults to the value of 'serasoft.default.mail.destination.addresses'|\${serasoft.default.mail.destination.addresses}|
|serasoft.errors.mail.destination.addresses|Set of email addresses to send error feedback emails to. Email addresses are separated by spaces. It can includes the default addresses if needed. It defaults to the value of 'serasoft.default.mail.destination.addresses'|\${serasoft.default.mail.destination.addresses}|
|serasoft.lock.mail.destination.addresses|Set of feedback's email addresses to send because a lock is present. Email addresses are separated by spaces. It can includes the default addresses if needed. It defaults to the value of 'serasoft.default.mail.destination.addresses'|\${serasoft.default.mail.destination.addresses}|
|serasoft.notactive.mail.destination.addresses|Set of feedback's email addresses to send because the process is not active. Email addresses are separated by spaces. It can includes the default addresses if needed. It defaults to the value of 'serasoft.default.mail.destination.addresses'|\${serasoft.default.mail.destination.addresses}|
|serasoft.application.error.mail.destination.addresses|Set of email addresses to send application's error feedback emails to. Email addresses are separated by spaces. It can includes the default addresses if needed. It defaults to the value of 'serasoft.default.mail.destination.addresses'|\${serasoft.default.mail.destination.addresses}|
|serasoft.success.mail.text|Sample text for the success feedback email. It includes the base process name, hostname, and log file name|The process ${p_base_process_name} running on server ${v_hostname} was terminated successfully. Execution's log file available at: ${p_logfile_name}. PLEASE DO NOT REPLAY TO THIS EMAIL!|
|serasoft.error.mail.text|Sample text message for the error feedback email. It includes the log file name|The process was terminated abnormally because of an Exception. Execution's log file available at: ${p_logfile_name}. PLEASE DO NOT REPLAY TO THIS EMAIL!|
|serasoft.lock.mail.text|Sample text message used because a process cannot be started because a lock occurs. It includes the base process name, hostname, last job run timestamp, and log file name|The process ${p_base_process_name} running on server ${v_hostname} can't be started because same process started at ${v_last_instance_start_timestamp} is not yet terminated. Execution's log file available at: ${p_logfile_name}. PLEASE DO NOT REPLAY TO THIS EMAIL!|
|serasoft.application.error.mail.text|Sample text message used when an application error occurs. It includes the log file name and mentions that detailed exceptions are in the attachment|During process's execution we collected some exceptions on integrations_log_details. The detailed list of exception is in the attachment to this email.<p>If needed, execution's log file is available at: ${p_logfile_name}. PLEASE DO NOT REPLAY TO THIS EMAIL!|
|serasoft.notactive.mail.text|Sample text message used when a process cannot be started because it is not active. It includes the base process name, hostname, and log file name|The process ${p_base_process_name} running on server ${v_hostname} can't be started because is set to not active. Execution's log file available at: ${p_logfile_name}. PLEASE DO NOT REPLAY TO THIS EMAIL!|

---
