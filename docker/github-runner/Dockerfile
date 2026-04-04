FROM ghcr.io/actions/actions-runner:latest

USER root

# Install Azure CLI and other tools needed by CI workflows
RUN apt-get update -qq && \
    apt-get install -y -qq \
      curl \
      jq \
      unzip \
      apt-transport-https \
      lsb-release \
      gnupg && \
    # Azure CLI
    curl -sL https://aka.ms/InstallAzureCLIDeb | bash && \
    # Terraform
    TERRAFORM_VERSION="1.9.8" && \
    curl -sLo /tmp/terraform.zip "https://releases.hashicorp.com/terraform/${TERRAFORM_VERSION}/terraform_${TERRAFORM_VERSION}_linux_amd64.zip" && \
    unzip -q /tmp/terraform.zip -d /usr/local/bin/ && \
    rm /tmp/terraform.zip && \
    # PostgreSQL client
    apt-get install -y -qq postgresql-client && \
    # Python 3 + pip (for provisioning scripts)
    apt-get install -y -qq python3 python3-pip && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

USER runner

ENTRYPOINT ["/entrypoint.sh"]
