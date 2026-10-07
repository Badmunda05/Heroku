FROM python:3.12.7-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends git build-essential \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

COPY . /BAD/

WORKDIR /BAD

RUN python -m pip install --no-cache-dir --upgrade pip setuptools \
    && pip install --no-cache-dir --upgrade --requirement requirements.txt

CMD ["python3", "-m", "BAD"]
