"""DEMO: changes trained data and writes camera SD. Review before running."""
from huskylens import HuskyLens

cam = HuskyLens(tx=17, rx=16)
if not cam.ping():
    raise OSError('HuskyLens offline')

cam.set_algorithm('OBJECT_TRACKING')
# Teach ID 1 only after displaying the desired target to the camera:
# cam.learn(1)
# cam.set_custom_name(1, 'ALVO')
cam.custom_text('CAROLINE BOT', 80, 20)

# SD card required; operates on camera's SD, not the ESP32:
# cam.save_photo()
# cam.save_screenshot()
# cam.save_model(1)
# cam.load_model(1)   # WARNING: overwrites loaded learning state
# cam.forget()        # WARNING: deletes learning for current algorithm

print(cam.get_blocks())
# cam.clear_text()
