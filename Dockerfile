FROM python:3.8.10-slim as builder

WORKDIR /app
ENV PYTHONUNBUFFERED 1

COPY ./asterisk ./asterisk/
COPY requirements.txt setup.py README.rst ./
RUN python setup.py install
RUN pip install -r requirements.txt

COPY . .

CMD python call-manager/call-manager.py
