#!/bin/bash
set -e

MONGO_INIT_HOST=${MONGO_INIT_HOST:-mongo}
MONGO_INIT_PORT=${MONGO_INIT_PORT:-27017}
MONGO_INIT_DATABASE=${MONGO_INIT_DATABASE:-todo}
MONGO_INIT_USERNAME=${MONGO_INIT_USERNAME:-myuser}
MONGO_INIT_PASSWORD=${MONGO_INIT_PASSWORD:-mypassword}

until mongosh --host "$MONGO_INIT_HOST:$MONGO_INIT_PORT" --eval "db.adminCommand('ping')" > /dev/null 2>&1; do
  echo "Waiting for MongoDB to start on $MONGO_INIT_HOST:$MONGO_INIT_PORT..."
  sleep 2
done

echo "MongoDB started. Initializing database '$MONGO_INIT_DATABASE'..."

mongosh --host "$MONGO_INIT_HOST:$MONGO_INIT_PORT" <<EOF
use $MONGO_INIT_DATABASE
db.createUser(
  {
    user: "$MONGO_INIT_USERNAME",
    pwd: "$MONGO_INIT_PASSWORD",
    roles: [ { role: "readWrite", db: "$MONGO_INIT_DATABASE" } ]
  }
)

// Optional: Create initial collections
db.createCollection("tasks")

// Optional: Seed with a default board (you might want to handle board creation differently later)
db.createCollection("boards")
db.boards.insertOne({ _id: "default_board", name: "My First Board" })

EOF

echo "MongoDB initialization complete."