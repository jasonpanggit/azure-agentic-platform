ARG BASE_IMAGE
FROM ${BASE_IMAGE}

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . ./finops/

CMD ["python", "-m", "finops.agent"]
