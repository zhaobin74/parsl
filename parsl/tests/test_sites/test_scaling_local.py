import parsl
from parsl import *
#from nose.tools import nottest
import os
import time
import shutil
import argparse
from parsl.execution_provider.local.local import Local
parsl.set_stream_logger()

def test_config_A ():

    local = Local(config={'site' : 'Local'})

    x = local.submit("ipengine ", blocksize=1)
    print("Started : ", x)
    local.status([x])
    time.sleep(3)
    y = local.submit("ipengine ", blocksize=1)
    print("Started : ", y)
    time.sleep(3)
    #stats = local.status([x,y])
    
    print(local.cancel([x,y]))
    print(local.status([x, y]))

if __name__ == "__main__" :

    test_config_A()
    #test_config_B
    #test_config_C
