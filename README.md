# Hop's Process Template

This template gives a Hop project a predefined structure to manage configuration files and process from within a same bundle that can easily be distributed.

## Liquibase versioning

We adopt Liquibase in order to keep `config` and `logs` tables up-to-date.

So you must have already installed liquibase on the target machine

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

---


More to come soon...

