#!/bin/bash

# Exit immediately if a command exits with a non zero status
set -e
# Treat unset variables as an error when substituting
set -u

function process_init_files() {
	user=$1
	password=$2
	folder=$3
	if [ -d "$folder" ]; then
	  echo "Multiple scripts found for user $user"
      for f in $folder/*; do
		  echo "Processing $f"
		  case "$f" in
			  *.sh)     echo "$0: running $f"; . "$f" ;;
			  *.sql)    echo "$0: running $f"; PGPASSWORD=$password psql -v ON_ERROR_STOP=1 --username "$user" --dbname "$user"  -f "$f" ;;
		  esac
	  done
	fi
}

user=$1
pswd=$2
init_folder=$3

process_init_files $user $pswd $init_folder


echo "Database initialization complete."
