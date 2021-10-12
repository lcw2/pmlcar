#!/usr/bin/env python3
"""
Scripts to drive a pml car and train a model for it.
Usage:
    main.py (drive) [--model=<model>] [--tub=<tub1,tub2,...tub>]
    main.py (train) [--model=<model>] [--tub=<tub1,tub2,...tub>]

Options:
    -h --help        Show this screen.
    --tub=<tub>   List of paths tubs. Comma separated. Use quotes to use wildcards. ie "~/tubs"
    --model=<model>  Select a model of Deep learning
"""
import os

from docopt import docopt

from config import load_config
from parts.camera import PiCamera
from parts.clock import Timestamp
from parts.datastore import TubHandler,TubGroup
from parts.keras import KerasLinear
from parts.transform import Lambda



def drive(config,model_path,tub_path):

    from parts.usbserial import CarEngine
    from vehicle import Vehicle
    from parts.web_controller import LocalWebController

    V = Vehicle()
    clock = Timestamp()
    V.add(clock, outputs=['timestamp'])

    cam = PiCamera(resolution=config.CAMERA_RESOLUTION)
    V.add(cam, outputs=['cam/image_array'], threaded=True)

    ctr = LocalWebController()
    V.add(ctr,
          inputs=['cam/image_array'],
          outputs=['user/angle', 'user/throttle','user/mode','recording'],
          threaded=True)

    #See if we should even run the pilot module
    #This is only needed because the part run condition only accepts boolean
    def pilot_condition(mode):
        if mode == 'user':
            return False
        else:
            return True

    pilot_condition_part = Lambda(pilot_condition)
    V.add(pilot_condition_part,inputs=['user/mode'],outputs=['run_pilot'])

    #Run the pilot if the mode is not user
    kl = KerasLinear()
    if not model_path:
        model_path = cfg.MODELS_PATH
        model_path = os.path.expanduser(model_path)
    kl.load(model_path)


    V.add(kl,inputs=['cam/image_array'],
          outputs =['pilot/angle','pilot/throttle'],
          run_condition='run_pilot')

    #Choose what inputs should change the car
    def drive_mode(mode,
                   user_angle,user_throttle,
                   pilot_angle,pilot_throttle):
        if mode == 'user':
            return user_angle,user_throttle
        else:
            return pilot_angle,pilot_throttle


    drive_mode_part = Lambda(drive_mode)
    V.add(drive_mode_part,inputs=['user/mode','user/angle','user/throttle',
                                  'pilot/angle','pilot/throttle'],
          outputs=['angle','throttle'])


    engine = CarEngine()
    V.add(engine, inputs=['angle', 'throttle'])

    # add tub to save data
    inputs = ['cam/image_array', 'user/angle', 'user/throttle', 'user/mode']
    types = ['image_array', 'float', 'float', 'str']

    if not tub_path:
        tub_path = cfg.DATA_PATH
    tub_path = os.path.expanduser(tub_path)

    th = TubHandler(path=tub_path)
    tub = th.new_tub_writer(inputs=inputs,types = types)

    V.add(tub, inputs=inputs,run_condition='recording')

    # run the vehicle
    V.start(rate_hz=config.DRIVE_LOOP_HZ,
            max_loop_count=config.MAX_LOOPS)


def train(cfg,model_path,tub_path):
    import tensorflow as tf
    gpus = tf.config.experimental.list_physical_devices('GPU')
    for gpu in gpus:
        tf.config.experimental.set_memory_growth(gpu, True)

    '''
    use the specified data in tub_names to train an artifical neural network
    saves the output trained model as model_name
    '''
    X_keys = ['cam/image_array']
    Y_keys = ['user/angle','user/throttle']

    kl = KerasLinear()

    if not tub_path:
        tub_path = cfg.DATA_PATH
    if not model_path:
        model_path = cfg.MODELS_PATH
    tub_path = os.path.expanduser(tub_path)

    tubgroup = TubGroup(tub_path)
    train_gen,val_gen = tubgroup.get_train_val_gen(X_keys,Y_keys,batch_size=cfg.BATCH_SIZE,
                                                   train_frac=cfg.TRAIN_TEST_SPLIT)

    model_path = os.path.expanduser(model_path)
    total_records = len(tubgroup.df)
    total_train = int(total_records * cfg.TRAIN_TEST_SPLIT)
    total_val = total_records - total_train
    steps_per_epoch = total_train // cfg.BATCH_SIZE

    kl.train(train_gen,val_gen,saved_model_path=model_path,steps= steps_per_epoch,train_split=cfg.TRAIN_TEST_SPLIT)


if __name__ == '__main__':
    args = docopt(__doc__)
    cfg = load_config()
    if args['drive']:
        tub = args['--tub']
        model = args['--model']
        drive(cfg,model_path=model,tub_path =tub)
    elif args['train']:
        tub = args['--tub']
        model = args['--model']
        train(cfg,model_path=model,tub_path=tub)
