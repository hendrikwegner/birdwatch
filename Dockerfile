FROM tensorflow/tensorflow:latest
MAINTAINER hendrikwegner
WORKDIR /root
RUN echo "deb https://packages.cloud.google.com/apt coral-edgetpu-stable main" | tee /etc/apt/sources.list.d/coral-edgetpu.list && curl https://packages.cloud.google.com/apt/doc/apt-key.gpg | apt-key add - && apt update
RUN pip install paho-mqtt && pip install telegram && pip install python-telegram-bot && apt install python3-pycoral -y && mkdir images

COPY bird.py ./
COPY labels.txt ./
COPY birds.tflite ./
CMD [ "python", "./bird.py"]