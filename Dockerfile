FROM ubuntu:14.04

RUN apt-get update \
    && apt-get install -y python3-pip

EXPOSE 3000

WORKDIR /app

CMD ["python3", "examples/html-form/server.py"]

COPY requirements.txt runtime.txt .
RUN pip3 install -r requirements.txt

COPY . /app
