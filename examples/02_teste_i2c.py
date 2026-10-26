from machine import Pin, I2C
from huskylens import HuskyLens
from time import sleep_ms

i2c = I2C(0, sda=Pin(21), scl=Pin(22), freq=100000)
print('I2C:', [hex(x) for x in i2c.scan()])
cam = HuskyLens(i2c=i2c)
print('Conectada:', cam.ping())
cam.set_algorithm('COLOR_RECOGNITION')
while True:
    print(cam.get_blocks())
    sleep_ms(250)
