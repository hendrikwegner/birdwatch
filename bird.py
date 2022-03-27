from datetime import datetime, timedelta
import time
import os
import json
import requests
import base64
import paho.mqtt.client as mqttClient

import numpy as np
from PIL import Image
from pycoral.adapters import classify
from pycoral.adapters import common
from pycoral.utils.dataset import read_label_file
from pycoral.utils.edgetpu import make_interpreter
from pycoral.utils.edgetpu import list_edge_tpus

import telegram

telegram_bot_token = os.getenv("TELEGRAM_BOT_TOKEN", '5160887123:AAH_MnMpnhfn7N6RsnRAtx2_rImJ75xSII4')
telegram_private = os.getenv("TELEGRAM_PRIVATE_ID", '5251738753')
telegram_group = os.getenv("TELEGRAM_GROUP_ID", '-799191878')
frigate_endpoint = os.getenv("FRIGATE_ENDPOINT", '192.168.123.4:5000')
mqtt_endpoint_host = os.getenv("MQTT_ENDPOINT_HOST", '192.168.123.4')
mqtt_endpoint_port = os.getenv("MQTT_ENDPOINT_PORT", 1883)
mqtt_user = os.getenv("MQTT_USER", 'hendrik')
mqtt_password = os.getenv("MQTT_PASSWORD", 'hendrikmqtt')

use_tpu_usb = os.getenv("USE_TPU_USB", False)
use_tpu_pci = os.getenv("USE_TPU_PCI", False)

debug_mode = os.getenv("DEBUG_MODE", False)

bot = telegram.Bot(token=telegram_bot_token)
bot.send_message(chat_id=telegram_private, text='Starting!', disable_notification=True )
print(list_edge_tpus())

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
    if (data['before']['label'] == "bird"):
        thumb = "http://"+frigate_endpoint+"/api/events/" + data['before']['id'] + "/thumbnail.jpg"
        r = requests.get(thumb, allow_redirects=True)
        #if (data['before']['camera'] == "Pond"):
        image = '/root/images/'+data['before']['id']+'.jpg'
        open(image, 'wb').write(r.content)
        #image atleast 100bytes or declare as broken
        if (os.stat(image).st_size > 100):
            inference(image, data)
        else:
            f = open("app.logs", "a")
            f.write()
            f.write(image+' broken!'+'\n')
            f.close()

#run birb detection
def inference(image_path, data):
    
    labels = read_label_file('./models/labels.txt')
    if use_tpu_usb:
        interpreter = make_interpreter('./models/birds.tflite', device="usb")
    elif use_tpu_pci:
        interpreter = make_interpreter('./models/birds.tflite', device="pci")
    else:
        interpreter = make_interpreter('./models/birds.tflite')
    interpreter.allocate_tensors()

    # Model must be uint8 quantized
    if common.input_details(interpreter, 'dtype') != np.uint8:
        raise ValueError('Only support uint8 input type.')

    size = common.input_size(interpreter)
    image = Image.open(image_path).convert('RGB').resize(size, Image.ANTIALIAS)

    # Image data must go through two transforms before running inference:
    # 1. normalization: f = (input - mean) / std
    # 2. quantization: q = f / scale + zero_point
    # The following code combines the two steps as such:
    # q = (input - mean) / (std * scale) + zero_point
    # However, if std * scale equals 1, and mean - zero_point equals 0, the input
    # does not need any preprocessing (but in practice, even if the results are
    # very close to 1 and 0, it is probably okay to skip preprocessing for better
    # efficiency; we use 1e-5 below instead of absolute zero).
    params = common.input_details(interpreter, 'quantization_parameters')
    scale = params['scales']
    zero_point = params['zero_points']
    mean = 128
    std = 128
    if abs(scale * std - 1) < 1e-5 and abs(mean - zero_point) < 1e-5:
        # Input data does not require preprocessing.
        common.set_input(interpreter, image)
    else:
        # Input data requires preprocessing
        normalized_input = (np.asarray(image) - mean) / (std * scale) + zero_point
        np.clip(normalized_input, 0, 255, out=normalized_input)
        common.set_input(interpreter, normalized_input.astype(np.uint8))

    # Run inference
    print('----INFERENCE TIME----')
    for _ in range(3):
        start = time.perf_counter()
        interpreter.invoke()
        inference_time = time.perf_counter() - start
        classes = classify.get_classes(interpreter, 1, 0)
        print('%.1fms' % (inference_time * 1000))

    print('-------RESULTS--------')
    for c in classes:
        if "Heron" in labels.get(c.id, c.id):
            bot.send_photo(chat_id=telegram_group, photo=open(image_path, 'rb'), caption='%s: %.5f' % (labels.get(c.id, c.id), c.score))
        print('%s: %.5f' % (labels.get(c.id, c.id), c.score))
        
        f = open("app.logs", "a")
        now = datetime.now() + timedelta(hours=1)
        f.write('%s: %.5f' % (labels.get(c.id, c.id), c.score) + '\n')
        f.close()
        bot.send_photo(chat_id=telegram_private, photo=open(image_path, 'rb'), caption='%s: %.5f' % (labels.get(c.id, c.id), c.score))


Connected = False   #global variable for the state of the connection
try:
    client = mqttClient.Client(os.uname()[1])               #create new instance
    client.username_pw_set(mqtt_user, password=mqtt_password)    #set username and password
    client.on_connect= on_connect                      #attach function to callback
    client.on_message= on_message                      #attach function to callback
      
    client.connect(mqtt_endpoint_host, port=mqtt_endpoint_port)          #connect to broker
      
    client.loop_start()        #start the loop
      
    while Connected != True:    #Wait for connection
        time.sleep(0.1)
      
    client.subscribe("frigate/events")
      
    try:
        while True:
            time.sleep(1)
      
    except KeyboardInterrupt:
        print("exiting")
        client.disconnect()
        client.loop_stop()

except:
    bot.send_message(chat_id=telegram_private, text='Bot crashed!', disable_notification=True)
    client.disconnect()
    client.loop_stop()

