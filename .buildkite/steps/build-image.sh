#!/bin/bash
set -euo pipefail

REVISION=$(git rev-parse HEAD)

set ${SOLANA_REVISION:=v1.7.9-resources}
set ${EVM_LOADER_REVISION:=4c00d4b010c3f915c582eded846e04fad9aec80e}

# Refreshing neonlabsorg/solana:latest image is required to run .buildkite/steps/build-image.sh locally
docker pull neonlabsorg/solana:${SOLANA_REVISION}

# Refreshing neonlabsorg/evm_loader:latest image is required to run .buildkite/steps/build-image.sh locally
docker pull neonlabsorg/evm_loader:${EVM_LOADER_REVISION}

docker build -t neonlabsorg/proxy:${REVISION} \
    --build-arg SOLANA_REVISION=${SOLANA_REVISION} \
    --build-arg EVM_LOADER_REVISION=${EVM_LOADER_REVISION} \
    .
