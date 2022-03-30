FROM tensorflow/tensorflow:latest

MAINTAINER Hendrik Wegner "mail@hendrikwegner.de"

WORKDIR /root

RUN echo "Europe/Stockholm" > /etc/timezone
RUN apt install -y tzdata ntpdate
RUN dpkg-reconfigure -f noninteractive tzdata

RUN echo "deb https://packages.cloud.google.com/apt coral-edgetpu-stable main" | tee /etc/apt/sources.list.d/coral-edgetpu.list
RUN curl https://packages.cloud.google.com/apt/doc/apt-key.gpg | apt-key add -
RUN apt update
RUN pip install paho-mqtt && pip install telegram && pip install python-telegram-bot 
RUN apt install -y python3-pycoral git

RUN git clone https://github.com/hendrikwegner/birdwatch.git
WORKDIR /root/birdwatch
CMD [ "/bin/sh", "./run.sh"]
