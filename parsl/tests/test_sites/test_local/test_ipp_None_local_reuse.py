from parsl import *
import parsl
import libsubmit

parsl.set_stream_logger()

print(parsl.__version__)
print(libsubmit.__version__)

from local import localIPPReuse as config
dfk = DataFlowKernel(config=config)

@App("python", dfk)
def python_app():
    import platform
    return "Hello from {0}".format(platform.uname())

@App("bash", dfk)
def bash_app(stdout=None, stderr=None):
    return 'echo "Hello from $(uname -a)" ; sleep 2'


def test_python():
    ''' Testing basic python functionality '''

    import os
    results = {}
    for i in range(0,2):
        results[i] = python_app()

    print("Waiting ....")
    print(results[0].result())


def test_bash():
    ''' Testing basic bash functionality '''

    import os
    fname = os.path.basename(__file__)

    x = bash_app(stdout="{0}.out".format(fname))
    print("Waiting ....")
    print(x.result())


if __name__ == "__main__" :

    test_python()
    test_bash()
