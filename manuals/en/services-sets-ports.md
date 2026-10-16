# Services: the object page, sets, ports

**The service page** (Packages & services → a service): the tabs **Overview** (status, ports, Homebrew notes), **Versions** (the latest and versioned formulae, e.g. `postgresql@16`: they install side by side, but only one can run on a port), **Settings** (the config editor with validation and a backup), **Log** (right on the page, “Refresh”). If a service is stopped and its port is taken by another process, a warning appears on the Overview.

**Sets** (Packages & services → **Sets**): ready bundles **Laravel** (nginx + PHP-FPM + MySQL + Redis + Mailpit), **Node.js** (PostgreSQL + Redis + Mailpit), **Python** (PostgreSQL + Redis + RabbitMQ) and **your own groups**. Buttons: “Start all”, “Stop all”, “Restart”, “Install the missing”. Services that are not installed are skipped, one that fails does not stop the others. Create your own group at the bottom: a name and ticks on the installed services.

**Ports** (Packages & services → **Ports**): who listens on which TCP port — the process, PID, address and access (“this computer only” or “from the network”). View only: the panel does not kill processes. If a service will not start, look here to see whether its port is taken.

**Catalog:** the “Recommended” list gained the groups “Database tools” (phpMyAdmin, pgAdmin 4, DbGate, mongosh, MongoDB Compass) and “Infrastructure” (etcd, Consul, Temporal, Neo4j, ClickHouse, Tomcat, Podman).
