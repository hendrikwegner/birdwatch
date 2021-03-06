from datetime import datetime, timedelta
import time
import os
import json
import requests
import base64
import paho.mqtt.client as mqttClient

import logging
from distutils.util import strtobool

import numpy as np
from PIL import Image
from pycoral.adapters import classify
from pycoral.adapters import common
from pycoral.utils.dataset import read_label_file
from pycoral.utils.edgetpu import make_interpreter
from pycoral.utils.edgetpu import list_edge_tpus

import telegram

def getEnv(key, defaultValue):
    value = os.getenv(key)
    if value is None or (len(value) == 0):
        return defaultValue
    return value
    
try:

    logging.basicConfig(filename='app.logs', filemode='a', format='%(asctime)s - %(message)s', datefmt='%d-%b-%y %H:%M:%S', level=logging.DEBUG)

    telegram_bot_token = getEnv("TELEGRAM_BOT_TOKEN", '5160887123:AAH_MnMpnhfn7N6RsnRAtx2_rImJ75xSII4')
    telegram_private = getEnv("TELEGRAM_PRIVATE_ID", '5251738753')
    telegram_group = getEnv("TELEGRAM_GROUP_ID", '-799191878')
    frigate_endpoint = getEnv("FRIGATE_ENDPOINT", '192.168.123.4:5000')
    mqtt_endpoint_host = getEnv("MQTT_ENDPOINT_HOST", '192.168.123.4')
    mqtt_endpoint_port = int(getEnv("MQTT_ENDPOINT_PORT", 1883))
    mqtt_user = getEnv("MQTT_USER", 'hendrik')
    mqtt_password = getEnv("MQTT_PASSWORD", 'hendrikmqtt')
    use_tpu_usb = bool(strtobool(getEnv("USE_TPU_USB", False)))
    use_tpu_pci = bool(strtobool(getEnv("USE_TPU_PCI", False)))
    debug_mode = bool(strtobool(getEnv("DEBUG_MODE", False)))

    bot = telegram.Bot(token=telegram_bot_token)
    bot.send_message(chat_id=telegram_private, text='Starting - Debug Mode: ' + str(debug_mode), disable_notification=True)

    logging.debug('Starting - Debug Mode: ' + str(debug_mode))
    logging.debug('Available TPU Devices: ' + str(list_edge_tpus()))


    def testrun():
        bot.send_message(chat_id=telegram_private, text='Testrun Starts', disable_notification=True)
        testimage = "/root/birdwatch/images/1648705663.60658-all9ja.jpg"
        check_results(inference(testimage), False)
        check_results(inference(testimage), False)
        bot.send_message(chat_id=telegram_private, text='Testrun Finished', disable_notification=True)

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
        if (data['before']['label'] == "bird") and (data['before']['camera'] == "Pond"):
            thumb = "http://"+frigate_endpoint+"/api/events/" + data['before']['id'] + "/thumbnail.jpg"
            r = requests.get(thumb, allow_redirects=True)
            image = '/root/birdwatch/images/'+data['before']['id']+'.jpg'
            logging.debug('Writing: ' + image)
            open(image, 'wb').write(r.content)
            #image atleast 100bytes or declare as broken
            if (os.stat(image).st_size > 100):
                result = inference(image)
                check_results(result, True)
            else:
                logging.debug(image+' broken!')


    #run birb detection
    def inference(image_path):
        
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
        start = time.perf_counter()
        interpreter.invoke()
        inference_time = time.perf_counter() - start
        classes = classify.get_classes(interpreter, 1, 0)
        print('%.1fms' % (inference_time * 1000))
        result = {'image': image_path}

        print('-------RESULTS--------')
        for c in classes:
            result.update({labels.get(c.id, c.id): float(c.score)})
            print('%s: %.5f' % (labels.get(c.id, c.id), c.score))
            logging.debug('%s: %.5f - ' % (labels.get(c.id, c.id), c.score))
        return result

    def check_results(results, send_alarm):
        for bird in results.items():
            if bird[0] == 'image':
                continue
            if "heron" in bird[0].lower() and bird[1] > 0.4:
                #heron with score over 0.4
                if send_alarm:
                    bot.send_photo(chat_id=telegram_group, photo=open(results['image'], 'rb'), caption='%s: %.5f' % (bird[0], bird[1]))
            if "background" not in bird[0].lower() and bird[1] > 0.25:
                bot.send_photo(chat_id=telegram_private, photo=open(results['image'], 'rb'), caption='%s: %.5f' % (bird[0], bird[1]))

                
                
    Connected = False   #global variable for the state of the connection
    if debug_mode:
        testimage = "/root/birdwatch/images/1648705663.60658-all9ja.jpg"
        while True:
            inference(testimage)
            time.sleep(5)
            print('loop done')
            logging.debug('loop done')
    else:
        testrun()

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

except Exception as e:
    bot.send_message(chat_id=telegram_private, text='Bot crashed!')
    logging.debug(str(e))
    if not debug_mode:
        client.disconnect()
        client.loop_stop()
