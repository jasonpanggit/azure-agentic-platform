ARG BASE_IMAGE
FROM ${BASE_IMAGE:-aap-agents-base:latest}

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . ./sre/

CMD ["python", "-m", "sre.agent"]
