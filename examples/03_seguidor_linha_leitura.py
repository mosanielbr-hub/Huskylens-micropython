"""Read line vector, calculate steering error; DOES NOT activate motors."""
from huskylens import HuskyLens
from time import sleep_ms

cam = HuskyLens(tx=17, rx=16)
if not cam.ping():
    raise OSError('Sem comunicacao com HuskyLens')
cam.set_algorithm('LINE_TRACKING')
sleep_ms(400)

while True:
    arrows = cam.get_arrows()
    if arrows:
        linha = arrows[0]
        erro = linha.x_target - 160  # camera width 320
        print('erro X:', erro, 'vetor:', linha)
        # Integrar com L298N / PID no main.py do Caroline Bot.
    else:
        print('Linha nao encontrada')
    sleep_ms(80)
