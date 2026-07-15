FROM postgres:16

# The upstream image executes these scripts only for a new data directory.
COPY db/chinook.sql /docker-entrypoint-initdb.d/01-chinook.sql
COPY db/demo-customer.sql /docker-entrypoint-initdb.d/02-demo-customer.sql
