FROM ubuntu:14.04

ADD . /app

RUN apt-get update
RUN apt-get install -y python3-pip
RUN pip3 install -r /app/requirements.txt

EXPOSE 3000

CMD ["python3", "/app/examples/html-form/server.py"]