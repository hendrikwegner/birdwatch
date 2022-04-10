from datetime import datetime, timedelta
import time
import os
import glob
import json
import requests
import base64
import paho.mqtt.client as mqttClient

import logging
from distutils.util import strtobool

from werkzeug.datastructures import ImmutableMultiDict
from flask import Flask, render_template, url_for, request, redirect, url_for
app = Flask(__name__)
app.config['TEMPLATES_AUTO_RELOAD'] = True

from tinydb import TinyDB, Query, where
db = TinyDB('/root/db.json')
db_images = db.table('images')

def getEnv(key, defaultValue):
    value = os.getenv(key)
    if value is None or (len(value) == 0):
        return defaultValue
    return value

#logging.basicConfig(filename='app.logs', filemode='a', format='%(asctime)s - %(message)s', datefmt='%d-%b-%y %H:%M:%S', level=logging.DEBUG)


frigate_endpoint = getEnv("FRIGATE_ENDPOINT", '192.168.123.4:5000')
mqtt_endpoint_host = getEnv("MQTT_ENDPOINT_HOST", '192.168.123.4')
mqtt_endpoint_port = int(getEnv("MQTT_ENDPOINT_PORT", 1883))
mqtt_user = getEnv("MQTT_USER", 'hendrik')
mqtt_password = getEnv("MQTT_PASSWORD", 'hendrikmqtt')


#mqtt connect
def on_connect(client, userdata, flags, rc):
    if rc == 0:
        print("Connected to broker")
        global Connected                #Use global variable
        Connected = True                #Signal connection 
    else:
        print("Connection failed")

#mqtt message recieved
def on_message(client, userdata, message):
    data = json.loads(message.payload.decode())
    url = "http://"+frigate_endpoint+"/api/events/" + data['before']['id'] + "/thumbnail.jpg"
    r = requests.get(url, allow_redirects=True)
    image_unique = '/root/birdwatch/static/'+data['before']['id']+'-'+ str(round(time.time(),2)).replace(".","-") +'.jpg'
    #image = './static/'+data['before']['id']+'.jpg'
    open(image_unique, 'wb').write(r.content)
    os.chdir("/root/birdwatch/static")

    unique = True

    for file in glob.glob(data['before']['id']+"*"):
        if file in image_unique:
            continue
        if open(file,"rb").read() == open(image_unique,"rb").read():
            unique = False
            #print("would remove file: " + file + " same as: " + image_unique)
            os.remove(file)

    if unique:    
        db_images.insert({'label': data['before']['label'], 'url': "http://192.168.123.4:8070"+image_unique[15:], "eventid": data['before']['id'], "camera": data['before']['camera']})
    

Connected = False   #global variable for the state of the connection
client = mqttClient.Client("classification-watcher")               #create new instance
client.username_pw_set(mqtt_user, password=mqtt_password)    #set username and password
client.on_connect= on_connect                      #attach function to callback
client.on_message= on_message                      #attach function to callback
client.connect(mqtt_endpoint_host, port=mqtt_endpoint_port)          #connect to broker
client.loop_start()        #start the loop
  
while Connected != True:    #Wait for connection
    time.sleep(0.1)
  
client.subscribe("frigate/events")


@app.route('/')
def index():
    return render_template('index.html', data=db_images.search(where('label') == "bird"), req=request.url)


@app.route('/train', methods = ['POST'])
def train():
    url = request.form.get("url")
    label = request.form.get("label")

    r = requests.post('http://192.168.123.4:8083/classificationbox/models/birds/teach', json={
            "class": label,
            "inputs": [
                {
                    "key": "bird",
                    "type": "image_url",
                    "value": url
                }
            ]
        })

    db_images.remove(Query().url == url)
    print(r.json())
    return redirect(url_for('index'))

@app.route('/predict', methods = ['POST'])
def predict():
    if request.form.get("predict-testdata"):
        url = request.form.get("predict-testdata")
        r = requests.post('http://192.168.123.4:8083/classificationbox/models/birds/predict', json={
                "inputs": [
                    {
                        "key": "bird",
                        "type": "image_url",
                        "value": url
                    }
                ]
            })
        print(r.json())
        return render_template('index.html', url=url, prediction=r.json(), data=db_images.search(where('label') == "bird"), req=request.url)


    img = request.files['img'].read()
    os.chdir("/root/birdwatch/static/uploads")
    filename = str(time.time()).replace(".","-")+".jpg"
    open(filename, 'wb').write(img)
    r = requests.post('http://192.168.123.4:8083/classificationbox/models/birds/predict', json={
                "inputs": [
                    {
                        "key": "bird",
                        "type": "image_url",
                        "value": "http://192.168.123.4:8070/static/uploads/"+filename
                    }
                ]
            })

    print(r.json())

    return render_template('index.html', results=r.json(), data=db_images.search(where('label') == "bird"), req=request.url)





try:
    app.run(debug = False, host = '0.0.0.0', port = 80, use_reloader = False)
    while True:
        time.sleep(1)
  
except KeyboardInterrupt:
    print("exiting")
    client.disconnect()
    client.loop_stop()
