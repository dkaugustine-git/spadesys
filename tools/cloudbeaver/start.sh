#!/bin/bash
# Start CloudBeaver, and restart it whenever Spadesys rewrites its list of connections.
# CloudBeaver only reads connection files at startup, so a restart is how new ones show up.
cd /opt/cloudbeaver || exit 1
LIST=workspace/GlobalConfiguration/.dbeaver/data-sources-spadesys.json

checksum() { md5sum "$LIST" 2>/dev/null; }

while true; do
  seen=$(checksum)
  ./run-server.sh &
  pid=$!
  while kill -0 "$pid" 2>/dev/null; do
    sleep 3
    if [ "$(checksum)" != "$seen" ]; then
      echo "Spadesys changed the connection list, restarting CloudBeaver"
      kill "$pid"
      wait "$pid"
      break
    fi
  done
  sleep 1
done
