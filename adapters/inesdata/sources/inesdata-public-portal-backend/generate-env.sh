
# Generate a .env file with some keys setted to random 16 bytes values, encoded as base64
# The keys are: SECRET_KEY, JWT_SECRET_KEY, JWT_REFRESH_TOKEN_SECRET_KEY

# The .env file will be generated in the same directory as this script

# Usage: ./generate-env.sh

# Exit on error
set -e

# Generate a random 16 bytes value as a base64 string
function generate_key {
  echo -n $RANDOM$RANDOM$RANDOM | base64
}

# Generate the .env file
echo "APP_KEYS=$(generate_key),$(generate_key),$(generate_key),$(generate_key)" > .env
echo "ADMIN_JWT_SECRET=$(generate_key)" >> .env
echo "JWT_SECRET=$(generate_key)" >> .env
echo "API_TOKEN_SALT=$(generate_key)" >> .env
echo "TRANSFER_TOKEN_SALT=$(generate_key)" >> .env

echo "The .env file has been generated in $(pwd)/.env"

