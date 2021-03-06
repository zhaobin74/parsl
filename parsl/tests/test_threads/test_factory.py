import os
import sys
import argparse

import parsl
from parsl import *

from parsl.app.app_factory import AppFactoryFactory, AppFactory

workers = ThreadPoolExecutor(max_workers=4)

@App('bash', workers)
def app_1(stderr='std.err', stdout='std.out'):
    cmd_line = "echo 'Hello world'"
    return cmd_line

def app_2(stderr='std.err', stdout='std.out'):
    cmd_line = "echo 'Hello world'"
    return cmd_line

def app_3(x):
    return x*2

def test_factory():
    appff = AppFactoryFactory('main')
    app_f = appff.make('bash', workers, app_2, walltime=60)
    assert type(app_f) == AppFactory , "AppFactoryFactory made the wrong type"

    app_f_2 = appff.make('python', workers, app_3, walltime=60)
    assert type(app_f_2) == AppFactory , "AppFactoryFactory made the wrong type"

def test_factory_names():
    appff = AppFactoryFactory('main')
    print(appff)
    print(appff.__repr__())


if __name__ == '__main__' :

    test_factory()
    test_factory_names()
