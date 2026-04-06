#!/bin/bash
# Container entrypoint — configures git credentials before starting the app.
# This script is optional; you can also mount a .gitconfig directly.

set -e

# Configure git identity for commits
git config --global user.email "ai-pr-agent@noreply.local"
git config --global user.name "AI PR Agent"

# If AZURE_DEVOPS_PAT is set, configure credential helper for Azure DevOps
if [ -n "$AZURE_DEVOPS_PAT" ] && [ -n "$AZURE_DEVOPS_ORG_URL" ]; then
    # Extract hostname from org URL
    ORG_HOST=$(echo "$AZURE_DEVOPS_ORG_URL" | sed 's|https*://||' | cut -d'/' -f1)

    # Configure git to use PAT for this host
    git config --global credential.helper store
    echo "https://ai-agent:${AZURE_DEVOPS_PAT}@${ORG_HOST}" > /home/agent/.git-credentials
    chmod 600 /home/agent/.git-credentials

    echo "✅ Git credentials configured for ${ORG_HOST}"
fi

# Clone target repo if workspace is empty
if [ -n "$GIT_REMOTE_URL" ] && [ ! -d "$GIT_REPO_PATH/.git" ]; then
    echo "📥 Cloning target repo into $GIT_REPO_PATH ..."
    git clone "$GIT_REMOTE_URL" "$GIT_REPO_PATH"
    echo "✅ Repo cloned."
fi

# Start the application
exec "$@"
