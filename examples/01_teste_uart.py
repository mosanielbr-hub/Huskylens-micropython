from huskylens import HuskyLens
from time import sleep_ms

cam = HuskyLens(tx=17, rx=16, timeout=700)
print('HuskyLens conectada:', cam.ping())
cam.set_algorithm('OBJECT_TRACKING')

while True:
    try:
        for obj in cam.get_blocks():
            print('ID:', obj.id, 'centro:', obj.x, obj.y,
                  'tamanho:', obj.width, obj.height)
    except OSError as erro:
        print('Camera:', erro)
    sleep_ms(150)
