"""Read HuskyLens line vectors and print their X offsets."""
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
        # Use o vetor lido conforme a necessidade da sua aplicação.
    else:
        print('Linha nao encontrada')
    sleep_ms(80)
