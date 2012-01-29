#!/bin/bash

set -e

if [ -e /tmp/finance.db ]
then
  rm -i /tmp/finance.db
fi

cd database_setup
sqlite3 /tmp/finance.db < schema.sql
cd ..
