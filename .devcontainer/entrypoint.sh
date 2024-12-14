#!/bin/bash

# Change permissions on the Docker socket
chown root:docker /var/run/docker-host.sock
chmod 660 /var/run/docker-host.sock

# Execute the original command
exec su devuser -c "$@"