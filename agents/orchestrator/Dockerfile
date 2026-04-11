ARG BASE_IMAGE
FROM ${BASE_IMAGE}

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . ./orchestrator/

CMD ["python", "-m", "orchestrator.agent"]
