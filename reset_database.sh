#!/bin/bash

set -e

rm /tmp/finance.db
cd database_setup
sqlite3 /tmp/finance.db < schema.sql
cd ..
