#!/bin/sh

echo "Initializing app..."

PUID=${PUID:-1000}
PGID=${PGID:-1000}

echo "-----------------"
echo -e "\033[1mRunning with:\033[0m"
echo "PUID=${PUID}"
echo "PGID=${PGID}"
echo "-----------------"

# Create the required directories with the correct permissions
echo "Setting up directories.."
mkdir -p /listenarr/config
chown -R ${PUID}:${PGID} /listenarr

# Start the application with the specified user permissions
echo "Running Listenarr..."
exec su-exec ${PUID}:${PGID} gunicorn src.Listenarr:app -c gunicorn_config.py
